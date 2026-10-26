"""Account routing and explicitly approved uploads, separate from the GPU queue."""
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx
from .clips import ClipLibrary
from .twitch import protect

PLATFORMS = ('youtube', 'tiktok')
SCOPES = {'youtube': 'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly',
          'tiktok': 'user.info.basic,video.upload'}
TOKEN_URLS = {'youtube': 'https://oauth2.googleapis.com/token', 'tiktok': 'https://open.tiktokapis.com/v2/oauth/token/'}


class Publishing:
    def __init__(self, store, data, client=None):
        self.store, self.data = store, Path(data)
        self.library = ClipLibrary(data)
        self.client = client or httpx.Client(timeout=60, follow_redirects=False)
        self.stopping = threading.Event()
        self.thread = None
        self.upload_times={}
        self.status_times={}
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS publishing_accounts (
                    id TEXT PRIMARY KEY, platform TEXT NOT NULL, remote_id TEXT NOT NULL,
                    name TEXT NOT NULL, credentials TEXT NOT NULL, expires REAL NOT NULL,
                    connected INTEGER NOT NULL DEFAULT 1, UNIQUE(platform,remote_id));
                CREATE TABLE IF NOT EXISTS publishing_routes (
                    streamer_id TEXT NOT NULL, platform TEXT NOT NULL, account_id TEXT NOT NULL UNIQUE,
                    PRIMARY KEY(streamer_id,platform));
                CREATE TABLE IF NOT EXISTS publishing_oauth (
                    state TEXT PRIMARY KEY, platform TEXT NOT NULL, verifier TEXT NOT NULL,
                    redirect_uri TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS publishing_jobs (
                    id TEXT PRIMARY KEY, filename TEXT NOT NULL, streamer_id TEXT NOT NULL,
                    account_id TEXT NOT NULL, platform TEXT NOT NULL, title TEXT NOT NULL,
                    description TEXT NOT NULL, privacy TEXT NOT NULL, kids INTEGER NOT NULL,
                    status TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL,
                    remote_id TEXT NOT NULL DEFAULT '', result_url TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL,
                    UNIQUE(filename,account_id));
            ''')

    def snapshot(self):
        return {'accounts': self.store.rows('SELECT id,platform,remote_id,name,connected FROM publishing_accounts ORDER BY platform,name'),
                'routes': self.store.rows('SELECT * FROM publishing_routes'),
                'jobs': self.store.rows('SELECT j.*,a.name AS account_name FROM publishing_jobs j JOIN publishing_accounts a ON a.id=j.account_id ORDER BY j.created DESC LIMIT 100')}

    def config(self):
        return {p: {'client_id': self.store.setting('publish_'+p+'_client_id', ''),
                    'secret_saved': bool(self.store.setting('publish_'+p+'_secret'))} for p in PLATFORMS}

    def configure(self, platform, client_id, secret):
        if platform not in PLATFORMS: raise ValueError('Неизвестная площадка')
        if not client_id.strip(): raise ValueError('Укажите Client ID / Client key')
        # A credential change must not silently affect previously connected accounts.
        if self.store.rows('SELECT id FROM publishing_accounts WHERE platform=? AND connected=1', (platform,)):
            if client_id.strip() != self.config()[platform]['client_id'] or secret:
                raise ValueError('Сначала отключите аккаунты этой площадки перед сменой OAuth-приложения')
        encrypted = protect(secret) if secret else self.store.setting('publish_'+platform+'_secret', '')
        if not encrypted: raise ValueError('Укажите Client Secret')
        with self.store.lock, self.store.connect() as db:
            for key, value in [('client_id',client_id.strip()),('secret',encrypted)]:
                db.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           ('publish_'+platform+'_'+key,json.dumps(value)))

    def application(self, platform):
        if platform not in PLATFORMS: raise ValueError('Неизвестная площадка')
        client_id = self.store.setting('publish_'+platform+'_client_id', '')
        secret = self.store.setting('publish_'+platform+'_secret', '')
        if not client_id or not secret: raise ValueError('Настройте OAuth-приложение в разделе аккаунтов')
        return client_id, protect(secret, decrypt=True)

    def begin_oauth(self, platform, base):
        client_id, _ = self.application(platform)
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        redirect = base.rstrip('/')+'/api/publishing/oauth/'+platform+'/callback'
        self.store.execute('DELETE FROM publishing_oauth WHERE expires<?', (time.time(),))
        self.store.execute('INSERT INTO publishing_oauth VALUES (?,?,?,?,?)',
                           (state,platform,protect(verifier),redirect,time.time()+600))
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = digest.hex() if platform == 'tiktok' else base64.urlsafe_b64encode(digest).decode().rstrip('=')
        params = {'response_type':'code','redirect_uri':redirect,'scope':SCOPES[platform],
                  'state':state,'code_challenge':challenge,'code_challenge_method':'S256'}
        if platform == 'youtube':
            params.update(client_id=client_id,access_type='offline',prompt='consent select_account')
            endpoint = 'https://accounts.google.com/o/oauth2/v2/auth'
        else:
            params['client_key'] = client_id
            endpoint = 'https://www.tiktok.com/v2/auth/authorize/'
        return state, endpoint+'?'+urlencode(params)

    def finish_oauth(self, platform, state, cookie, code):
        if not state or not cookie or not hmac.compare_digest(state,cookie): raise ValueError('OAuth-сессия не совпадает. Начните подключение заново')
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM publishing_oauth WHERE state=? AND platform=? AND expires>?', (state,platform,time.time())).fetchone()
            if not row: raise ValueError('OAuth-сессия истекла или уже использована')
            row = dict(row)
            db.execute('DELETE FROM publishing_oauth WHERE state=?',(state,))
        client_id, secret = self.application(platform)
        payload = {'grant_type':'authorization_code','code':code,'redirect_uri':row['redirect_uri'],
                   'code_verifier':protect(row['verifier'],decrypt=True),'client_secret':secret,
                   'client_id' if platform=='youtube' else 'client_key':client_id}
        tokens = self.checked(self.client.post(TOKEN_URLS[platform],data=payload), 'Подключение OAuth')
        if not tokens.get('access_token') or not tokens.get('refresh_token'): raise ValueError('Площадка не предоставила длительный доступ. Подключите аккаунт заново')
        granted = set(tokens.get('scope','').replace(',',' ').split())
        if not set(SCOPES[platform].replace(',',' ').split()) <= granted: raise ValueError('Не предоставлены необходимые разрешения аккаунта')
        headers = {'Authorization':'Bearer '+tokens['access_token']}
        if platform == 'youtube':
            data = self.checked(self.client.get('https://www.googleapis.com/youtube/v3/channels',params={'part':'snippet','mine':'true'},headers=headers),'Проверка YouTube-канала')
            if len(data.get('items',[])) != 1: raise ValueError('Выберите конкретный YouTube-канал и подключите его заново')
            remote, name = data['items'][0]['id'], data['items'][0]['snippet']['title']
        else:
            data = self.checked(self.client.get('https://open.tiktokapis.com/v2/user/info/',params={'fields':'open_id,display_name'},headers=headers),'Проверка TikTok-аккаунта')
            user = data.get('data',{}).get('user',{})
            remote, name = user.get('open_id'), user.get('display_name')
            if not remote or remote != tokens.get('open_id'): raise ValueError('Не удалось подтвердить TikTok-аккаунт')
        existing = self.store.rows('SELECT id FROM publishing_accounts WHERE platform=? AND remote_id=?',(platform,remote))
        key = existing[0]['id'] if existing else uuid.uuid4().hex
        self.store.execute('INSERT INTO publishing_accounts VALUES (?,?,?,?,?,?,1) ON CONFLICT(platform,remote_id) DO UPDATE SET name=excluded.name,credentials=excluded.credentials,expires=excluded.expires,connected=1',
                           (key,platform,remote,name,protect(json.dumps(tokens)),time.time()+int(tokens.get('expires_in',3600))))
        return key

    @staticmethod
    def checked(response, action):
        if not response.is_success: raise ValueError(action+f': площадка вернула HTTP {response.status_code}')
        data = response.json()
        if data.get('error') and (not isinstance(data['error'],dict) or data['error'].get('code') not in (None,'ok')):
            raise ValueError(action+': площадка отклонила запрос; проверьте разрешения и ограничения аккаунта')
        return data

    def bind(self, streamer_id, platform, account_id):
        if not any(s['id']==streamer_id for s in self.store.streamers()): raise ValueError('Стример не найден')
        if platform not in PLATFORMS: raise ValueError('Неизвестная площадка')
        with self.store.lock, self.store.connect() as db:
            if not account_id:
                db.execute('DELETE FROM publishing_routes WHERE streamer_id=? AND platform=?',(streamer_id,platform));return
            a = db.execute('SELECT * FROM publishing_accounts WHERE id=? AND platform=? AND connected=1',(account_id,platform)).fetchone()
            if not a: raise ValueError('Подключённый аккаунт этой площадки не найден')
            other = db.execute('SELECT streamer_id FROM publishing_routes WHERE account_id=? AND streamer_id<>?',(account_id,streamer_id)).fetchone()
            if other: raise ValueError('Этот аккаунт уже закреплён за другим стримером')
            db.execute('INSERT INTO publishing_routes VALUES (?,?,?) ON CONFLICT(streamer_id,platform) DO UPDATE SET account_id=excluded.account_id', (streamer_id,platform,account_id))

    def owner(self, filename):
        path = self.library.path(filename)
        meta = self.library.metadata(path)
        owner = meta.get('publisher_streamer_id')
        if not owner:
            source = json.loads(path.with_suffix('.plan.json').read_text(encoding='utf-8'))['source_id']
            for row in self.store.rows('SELECT metadata FROM jobs WHERE source_id=? ORDER BY created DESC',(source,)):
                job = json.loads(row['metadata'])
                owner = job.get('streamer_id')
                parent = self.store.job(job.get('recording_job') or job.get('live_session') or '')
                if not owner and parent: owner = parent['metadata'].get('streamer_id')
                if owner: break
        return owner if any(s['id']==owner for s in self.store.streamers()) else None

    def assign(self, filename, streamer_id):
        if not any(s['id']==streamer_id for s in self.store.streamers()): raise ValueError('Стример не найден')
        if self.store.rows("SELECT id FROM publishing_jobs WHERE filename=? AND status NOT IN ('cancelled','failed')",(filename,)):
            raise ValueError('Для ролика уже есть отправка; его принадлежность менять нельзя')
        path = self.library.path(filename)
        self.library.write_metadata(path,{**self.library.metadata(path),'publisher_streamer_id':streamer_id})

    def enqueue(self, filename, account_ids, title, description, privacy, kids):
        path = self.library.path(filename)
        owner = self.owner(filename)
        if not owner: raise ValueError('Сначала явно укажите, какому стримеру принадлежит ролик')
        if not account_ids or len(account_ids)!=len(set(account_ids)): raise ValueError('Выберите аккаунты назначения')
        credit=self.library.metadata(path).get('background_credit',{})
        if credit.get('source_url') and credit['source_url'] not in description:
            description+='\n\nФоновое видео: '+credit.get('author','')+' — '+credit.get('title','')+'\n'+credit['source_url']+'\n'+credit.get('license','')+' '+credit.get('license_url','')+'\nБез звука, кадрирование и повтор.'
        created=[]
        with self.store.lock, self.store.connect() as db:
            for key in account_ids:
                account=db.execute('SELECT a.* FROM publishing_accounts a JOIN publishing_routes r ON r.account_id=a.id WHERE a.id=? AND a.connected=1 AND r.streamer_id=?',(key,owner)).fetchone()
                if not account: raise ValueError('Аккаунт не привязан к стримеру этого ролика')
                if account['platform']=='youtube' and (privacy not in ('private','unlisted','public') or kids is None): raise ValueError('Выберите доступ и отметку детского контента для YouTube')
                if account['platform']=='youtube' and (not title.strip() or len(title)>100): raise ValueError('Название YouTube должно содержать 1–100 символов')
                if account['platform']=='tiktok' and path.stat().st_size>4*1024**3:raise ValueError('Для TikTok файл должен быть не больше 4 ГБ')
                if account['platform']=='tiktok':
                    info=json.loads(path.with_suffix('.probe.json').read_text(encoding='utf-8'))
                    if float(info['format']['duration'])>600:raise ValueError('TikTok Upload принимает ролики до 10 минут. Отправьте длинную подборку на YouTube')
                if len(description)>5000: raise ValueError('Описание слишком длинное')
                if db.execute('SELECT id FROM publishing_jobs WHERE filename=? AND account_id=?',(filename,key)).fetchone(): raise ValueError('Этот ролик уже был добавлен для данного аккаунта')
                job_id=uuid.uuid4().hex;now=time.time()
                db.execute('INSERT INTO publishing_jobs(id,filename,streamer_id,account_id,platform,title,description,privacy,kids,status,total,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (job_id,filename,owner,key,account['platform'],title,description,privacy or 'private',int(bool(kids)),'queued',path.stat().st_size,now,now))
                created.append(job_id)
        return created

    def update(self,key,**values):
        if not set(values)<={'status','sent','remote_id','result_url','error'}: raise ValueError('Invalid publishing update')
        self.store.execute('UPDATE publishing_jobs SET '+','.join(k+'=?' for k in values)+',updated=? WHERE id=?',(*values.values(),time.time(),key))

    def token(self, account):
        tokens=json.loads(protect(account['credentials'],decrypt=True))
        if account['expires']>time.time()+120:return tokens['access_token']
        key,secret=self.application(account['platform'])
        fresh=self.checked(self.client.post(TOKEN_URLS[account['platform']],data={'grant_type':'refresh_token','refresh_token':tokens['refresh_token'],'client_secret':secret,'client_id' if account['platform']=='youtube' else 'client_key':key}),'Обновление доступа')
        if not fresh.get('access_token'):raise ValueError('Повторно подключите аккаунт')
        tokens.update(fresh)
        self.store.execute('UPDATE publishing_accounts SET credentials=?,expires=? WHERE id=?',(protect(json.dumps(tokens)),time.time()+int(fresh.get('expires_in',3600)),account['id']))
        return tokens['access_token']

    def cancelled(self,key):
        row=self.store.rows('SELECT status FROM publishing_jobs WHERE id=?',(key,))[0]
        if self.stopping.is_set() or row['status']=='cancel_requested':raise InterruptedError()

    @staticmethod
    def upload_url(url, platform):
        parsed=urlparse(url)
        suffix='.googleapis.com' if platform=='youtube' else '.tiktokapis.com'
        if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith(suffix) or parsed.username or parsed.port not in (None,443):
            raise ValueError('Площадка вернула недопустимый адрес загрузки')
        return url

    def process(self, job):
        key=job['id'];attempted=False
        try:
            path=self.library.path(job['filename'])
            if path.stat().st_size != job['total']:raise ValueError('Файл изменился после подтверждения')
            if self.owner(job['filename']) != job['streamer_id']:raise ValueError('Принадлежность ролика изменилась')
            accounts=self.store.rows('SELECT * FROM publishing_accounts WHERE id=? AND connected=1',(job['account_id'],))
            routes=self.store.rows('SELECT * FROM publishing_routes WHERE streamer_id=? AND account_id=?',(job['streamer_id'],job['account_id']))
            if not accounts or not routes:raise ValueError('Аккаунт отключён или привязка изменилась; отправка остановлена')
            self.cancelled(key)
            token=self.token(accounts[0]);headers={'Authorization':'Bearer '+token};size=job['total']
            if job['platform']=='youtube':
                init=self.client.post('https://www.googleapis.com/upload/youtube/v3/videos',params={'uploadType':'resumable','part':'snippet,status'},headers={**headers,'X-Upload-Content-Length':str(size),'X-Upload-Content-Type':'video/mp4'},json={'snippet':{'title':job['title'],'description':job['description'],'categoryId':'20'},'status':{'privacyStatus':job['privacy'],'selfDeclaredMadeForKids':bool(job['kids'])}})
                if not init.is_success:raise ValueError(f'YouTube: HTTP {init.status_code} при создании загрузки')
                url=self.upload_url(init.headers.get('location',''),'youtube');chunk=8*1024**2;count=(size+chunk-1)//chunk
            else:
                delay=max(0,11-(time.monotonic()-self.upload_times.get(job['account_id'],-100)))
                if delay:self.stopping.wait(delay)
                self.cancelled(key)
                self.upload_times[job['account_id']]=time.monotonic()
                chunk=min(size,16*1024**2);count=max(1,size//chunk)
                init=self.checked(self.client.post('https://open.tiktokapis.com/v2/post/publish/inbox/video/init/',headers=headers,json={'source_info':{'source':'FILE_UPLOAD','video_size':size,'chunk_size':chunk,'total_chunk_count':count}}),'Загрузка в TikTok')
                data=init['data'];url=self.upload_url(data['upload_url'],'tiktok');self.update(key,remote_id=data['publish_id'])
            with path.open('rb') as stream:
                sent=0
                for index in range(count):
                    self.cancelled(key)
                    amount=size-sent if index==count-1 else chunk
                    payload=stream.read(amount)
                    attempted=True
                    result=self.client.put(url,headers={'Content-Type':'video/mp4','Content-Range':f'bytes {sent}-{sent+len(payload)-1}/{size}',**(headers if job['platform']=='youtube' else {})},content=payload)
                    if result.status_code not in (200,201,206,308):raise ValueError(f'Площадка прервала загрузку: HTTP {result.status_code}')
                    sent+=len(payload);self.update(key,sent=sent)
                if job['platform']=='youtube':
                    remote=self.checked(result,'Ответ YouTube').get('id')
                    if not remote:raise ValueError('YouTube не подтвердил ID ролика')
                    self.update(key,status='uploaded',remote_id=remote,result_url='https://www.youtube.com/watch?v='+remote)
                else:self.update(key,status='processing',error='Файл передан. TikTok ещё обрабатывает загрузку.')
        except InterruptedError:
            self.update(key,status='attention' if attempted else 'cancelled',error='Отправка прервана. Проверьте аккаунт перед новой попыткой.' if attempted else 'Отправка отменена')
        except Exception as exc:
            # Never persist provider bodies or exception strings: they may contain tokens/URLs.
            detail=str(exc) if type(exc) is ValueError else 'Проверьте подключение аккаунта и сеть.'
            self.update(key,status='attention' if attempted else 'failed',error='Отправка не завершена. '+detail+' Перед повтором проверьте сам аккаунт.')

    def check_tiktok(self,job):
        if time.monotonic()-self.status_times.get(job['account_id'],-100)<2.5:return
        self.status_times[job['account_id']]=time.monotonic()
        try:
            account=self.store.rows('SELECT * FROM publishing_accounts WHERE id=? AND connected=1',(job['account_id'],))
            if not account:raise ValueError('Account disconnected')
            data=self.checked(self.client.post('https://open.tiktokapis.com/v2/post/publish/status/fetch/',headers={'Authorization':'Bearer '+self.token(account[0])},json={'publish_id':job['remote_id']}),'Статус TikTok')['data']
            if data.get('status') in ('SEND_TO_USER_INBOX','PUBLISH_COMPLETE'):
                self.update(job['id'],status='inbox',error='TikTok подтвердил передачу. Проверьте уведомление и завершите публикацию в приложении.')
            elif data.get('status')=='FAILED':self.update(job['id'],status='attention',error='TikTok отклонил обработку. Проверьте аккаунт; автоматический повтор отключён.')
            else:self.update(job['id'],status='processing')
        except Exception:self.update(job['id'],status='attention',error='Не удалось подтвердить результат TikTok. Проверьте аккаунт перед повторной отправкой.')

    def start(self):
        self.store.execute("UPDATE publishing_jobs SET status='attention',error='Работа прервана. Проверьте аккаунт: автоматический повтор отключён во избежание дублей.' WHERE status IN ('uploading','cancel_requested')")
        def loop():
            while not self.stopping.wait(.7):
                with self.store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    row=db.execute("SELECT * FROM publishing_jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                    if row:db.execute("UPDATE publishing_jobs SET status='uploading',updated=? WHERE id=?",(time.time(),row['id']))
                if row:self.process(dict(row))
                else:
                    waiting=self.store.rows("SELECT * FROM publishing_jobs WHERE platform='tiktok' AND status='processing' AND updated<? ORDER BY updated LIMIT 1",(time.time()-10,))
                    if waiting:self.check_tiktok(waiting[0])
        self.thread=threading.Thread(target=loop,name='publishing-queue',daemon=True);self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread:self.thread.join(timeout=3)
        if not self.thread or not self.thread.is_alive():self.client.close()

    def disconnect(self,key):
        if self.store.rows("SELECT id FROM publishing_jobs WHERE account_id=? AND status IN ('queued','uploading','cancel_requested')",(key,)):
            raise ValueError('Сначала отмените отправки этого аккаунта')
        self.store.execute("UPDATE publishing_accounts SET connected=0,credentials='' WHERE id=?",(key,))

    def cancel(self,key):
        rows=self.store.rows('SELECT * FROM publishing_jobs WHERE id=?',(key,))
        if not rows:raise ValueError('Отправка не найдена')
        if rows[0]['status']=='queued':self.update(key,status='cancelled')
        elif rows[0]['status']=='uploading':self.update(key,status='cancel_requested')

    def assert_deletable(self,filenames):
        identities={self.library.identity(self.library.path(name)) for name in filenames}
        for job in self.store.rows("SELECT filename FROM publishing_jobs WHERE status IN ('queued','uploading','cancel_requested')"):
            try:identity=self.library.identity(self.library.path(job['filename']))
            except FileNotFoundError:continue
            if identity in identities:raise ValueError('Сначала отмените отправку ролика в очереди площадок')

    def retry(self,key):
        rows=self.store.rows('SELECT * FROM publishing_jobs WHERE id=?',(key,))
        if not rows or rows[0]['status'] not in ('failed','cancelled'):raise ValueError('Повтор недоступен: сначала проверьте результат в аккаунте')
        self.update(key,status='queued',sent=0,error='')

    def reviewed_retry(self,key):
        rows=self.store.rows('SELECT * FROM publishing_jobs WHERE id=?',(key,))
        if not rows or rows[0]['status']!='attention':raise ValueError('Эта отправка не ожидает проверки')
        self.update(key,status='queued',sent=0,remote_id='',error='')
        self.store.log('Пользователь подтвердил отсутствие ролика в аккаунте и разрешил повтор отправки '+key)
