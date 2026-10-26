"""Helix monitoring and independent, recoverable Streamlink recordings."""
import base64
import ctypes
import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
import httpx
from .jobs import Cancelled
from .media import probe


def protect(value, decrypt=False):
    """Use the current Windows account's DPAPI; never store plaintext secrets."""
    if os.name != 'nt':
        raise RuntimeError('Хранение секрета доступно через Windows DPAPI')
    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    raw = base64.b64decode(value) if decrypt else value.encode('utf-8')
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise RuntimeError('Windows не смогла обработать секрет Twitch')
    try:
        data = ctypes.string_at(output.data, output.size)
        return data.decode('utf-8') if decrypt else base64.b64encode(data).decode('ascii')
    finally:
        ctypes.windll.kernel32.LocalFree(output.data)


class TwitchClient:
    def __init__(self, store):
        self.store = store
        self.token = None
        self.expires = 0
        self.identity = None
        self.lock = threading.Lock()

    def configured(self):
        return bool(self.store.setting('twitch_client_id') and self.store.setting('twitch_secret'))

    def headers(self):
        client_id = self.store.setting('twitch_client_id', '')
        secret = self.store.setting('twitch_secret', '')
        if not client_id or not secret:
            raise ValueError('Подключите Twitch в настройках приложения')
        with self.lock:
            if not self.token or time.time() > self.expires or self.identity != client_id:
                response = httpx.post('https://id.twitch.tv/oauth2/token', data={
                    'client_id': client_id, 'client_secret': protect(secret, decrypt=True),
                    'grant_type': 'client_credentials'}, timeout=15)
                if response.status_code != 200:
                    raise ValueError('Twitch отклонил Client ID или Client Secret. Проверьте настройки.')
                data = response.json()
                self.token = data['access_token']
                self.expires = time.time()+max(0, data['expires_in']-60)
                self.identity = client_id
            return {'Client-ID': client_id, 'Authorization': 'Bearer '+self.token}

    def get(self, resource, params):
        response = httpx.get('https://api.twitch.tv/helix/'+resource, params=params, headers=self.headers(), timeout=15)
        if response.status_code == 401:
            self.token = None
            response = httpx.get('https://api.twitch.tv/helix/'+resource, params=params, headers=self.headers(), timeout=15)
        response.raise_for_status()
        return response.json()['data']


class TwitchMonitor:
    def __init__(self, store, runner):
        self.store = store
        self.runner = runner
        self.client = TwitchClient(store)
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.recordings = {}
        self.capture_threads = {}
        self.thread = None
        self.error = None
        self.last_check = None

    def start(self):
        self.thread = threading.Thread(target=self.loop, name='twitch-monitor', daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.wake.set()
        for event in list(self.recordings.values()):
            event.set()
        if self.thread:
            self.thread.join(timeout=3)
        deadline = time.monotonic()+20
        for thread in list(self.capture_threads.values()):
            thread.join(timeout=max(0, deadline-time.monotonic()))

    def cancel(self, job_id):
        if job_id in self.recordings:
            self.recordings[job_id].set()

    def stop_streamer(self, streamer_id):
        for job in self.store.jobs():
            if job['kind'] == 'capture' and job['metadata'].get('streamer_id') == streamer_id and job['status'] == 'recording':
                self.cancel(job['id'])

    def record(self, streamer, force=False):
        if streamer.get('live_clip') and force:
            if not streamer['enabled'] or not streamer['auto_record']:raise ValueError('Для LIVE включите отслеживание и автозапись')
            # Manual connection does not claim Helix confirmed the channel live.
            streamer={**streamer,'status':'live','stream_id':streamer['stream_id'] or 'manual-'+uuid.uuid4().hex[:12]}
        if streamer['status'] != 'live' or not streamer['stream_id']:
            raise ValueError('Стример сейчас не в эфире или статус ещё не проверен')
        active = [j for j in self.store.jobs() if j['kind'] == 'capture' and j['status'] == 'recording'
                  and j['metadata'].get('streamer_id') == streamer['id']]
        if active:
            return active[0]
        dedupe = 'twitch:'+streamer['stream_id']
        existing = self.store.rows('SELECT id FROM jobs WHERE dedupe=?', (dedupe,))
        if existing and not force:
            return self.store.job(existing[0]['id'])
        if force:
            dedupe += ':manual:'+uuid.uuid4().hex
        metadata = {'streamer_id': streamer['id'], 'login': streamer['login'], 'stream_id': streamer['stream_id'],
                    'stream_title': streamer['title'], 'quality': streamer['quality'], 'chunks': [], 'bytes': 0}
        metadata['live_mode']=bool(streamer.get('live_clip'))
        metadata['adhd_mode']=bool(streamer.get('adhd_mode',False))
        job = self.store.create_job(f"Эфир {streamer['display_name']}", 'tw_'+uuid.uuid4().hex, kind='capture', metadata=metadata, dedupe=dedupe)
        self.store.update_job(job['id'], status='recording', stage='recording', started=time.time(), detail='Подключение к эфиру Twitch')
        cancel = self.recordings.setdefault(job['id'], threading.Event())
        thread = threading.Thread(target=self.capture, args=(job['id'], cancel), daemon=True, name='twitch-recording')
        self.capture_threads[job['id']] = thread
        thread.start()
        return self.store.job(job['id'])

    def capture(self, job_id, cancel):
        if self.store.job(job_id)['metadata'].get('live_mode'):
            return self.capture_live(job_id,cancel)
        job = self.store.job(job_id)
        meta = job['metadata']
        directory = self.runner.data/'recordings'/job_id
        directory.mkdir(parents=True, exist_ok=True)
        manifest = directory/'manifest.json'
        chunks = []
        failed = None
        container = 'rezak-record-'+job_id
        try:
            for index in range(96):  # At most 24 hours; each part is independently recoverable.
                current = next((s for s in self.store.streamers() if s['id'] == meta['streamer_id']), None)
                if cancel.is_set() or self.stopping.is_set() or not current or not current['enabled']:
                    break
                if index and current['status'] != 'live':
                    break
                if shutil.disk_usage(directory).free < 1024*1024*1024:
                    raise RuntimeError('Автозапись остановлена: осталось меньше 1 ГБ свободного места')
                part = directory/f'part-{index:04d}.ts'
                requested = time.time()
                quality = {'720p': '720p60,720p,480p,best', '1080p': '1080p60,1080p,720p,best', 'best': 'best'}[current['quality']]
                args = ['docker', 'compose', '--profile', 'recorder', 'run', '--rm', '-T', '--name', container,
                        'recorder', '--retry-streams', '10', '--retry-max', '3', '--stream-segment-attempts', '3',
                        '--stream-segment-timeout', '30', '--stream-timeout', '60', '--stream-segmented-duration', '900',
                        '--progress', 'no', '--output', f'/recordings/{job_id}/{part.name}',
                        'https://www.twitch.tv/'+current['login'], quality]
                self.runner.log(job_id, f'Запись части {index+1}. Лимит части — 15 минут; качество {current["quality"]}.')
                watcher_done = threading.Event()
                def size_watcher(done=watcher_done, part_index=index):
                    while not done.wait(2):
                        size = sum(p.stat().st_size for p in directory.glob('*.ts'))
                        latest = self.store.job(job_id)['metadata']
                        self.store.update_job(job_id, metadata={**latest, 'bytes': size}, detail=f'Идёт запись · часть {part_index+1}')
                watcher = threading.Thread(target=size_watcher, daemon=True)
                watcher.start()
                operation_error = None
                try:
                    self.runner.execute(args, job_id, cancel, timeout=1200)
                except Exception as exc:
                    operation_error = exc
                finally:
                    watcher_done.set()
                    watcher.join(timeout=3)
                    # Stop this recording container only; analysis containers are independent.
                    import subprocess
                    subprocess.run(['docker', 'stop', '--time', '5', container], capture_output=True, timeout=20)
                if part.exists() and part.stat().st_size > 1024:
                    info = probe(part)
                    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
                    duration = round(float(info['format']['duration'])*1000)
                    chunk = {'file': part.name, 'capture_requested_at': requested, 'capture_completed_at': time.time(),
                             'duration_ms': duration, 'start_pts': video.get('start_pts'), 'time_base': video.get('time_base'),
                             'bytes': part.stat().st_size, 'interrupted': operation_error is not None}
                    chunks.append(chunk)
                    temporary = manifest.with_suffix('.tmp')
                    temporary.write_text(json.dumps({**meta, 'chunks': chunks, 'timing_note': 'Wall-clock boundaries are capture request/completion times, not exact media clock synchronization.'}, ensure_ascii=False, indent=2), encoding='utf-8')
                    temporary.replace(manifest)
                    if current['auto_clip']:
                        source_id = f"tw_{current['login']}_{meta['stream_id']}_{index:04d}"
                        self.store.create_job(f"{current['display_name']} · часть {index+1}", source_id,
                                              input_path=part, metadata={'recording_job': job_id, 'streamer_id':current['id'], 'duration_ms': duration,'adhd_mode':bool(current.get('adhd_mode',False))})
                        self.runner.log(job_id, f'Часть {index+1} сохранена и добавлена в очередь нарезки', 'success')
                if operation_error:
                    if isinstance(operation_error, Cancelled) or cancel.is_set():
                        break
                    raise operation_error
                # Reconnect for the next bounded part. A wall-clock map records the boundary gap.
            message = f'Запись сохранена: {len(chunks)} частей' if chunks else 'Запись остановлена без полученного видео'
            self.store.update_job(job_id, status='done' if chunks else 'cancelled', finished=time.time(), detail=message,
                                  metadata={**meta, 'chunks': chunks, 'bytes': sum(c['bytes'] for c in chunks)})
            self.runner.log(job_id, message, 'success' if chunks else 'warning')
        except Exception as exc:
            failed = str(exc)
            self.store.update_job(job_id, status='error', finished=time.time(), error=failed, detail=failed,
                                  metadata={**meta, 'chunks': chunks, 'bytes': sum(c['bytes'] for c in chunks)})
            self.runner.log(job_id, failed, 'error')
        finally:
            self.recordings.pop(job_id, None)
            self.capture_threads.pop(job_id, None)

    def capture_live(self,job_id,cancel):
        from .live import LiveWindows,closed_parts
        import subprocess
        job=self.store.job(job_id);meta=job['metadata']
        directory=self.runner.data/'recordings'/job_id;directory.mkdir(parents=True,exist_ok=True)
        windows=LiveWindows(self,job_id,directory);done=threading.Event();errors=[]
        container='rezak-record-'+job_id
        def watch():
            while not done.wait(3):
                try:
                    current=next((s for s in self.store.streamers() if s['id']==meta['streamer_id']),None)
                    if not current or not current['enabled'] or not current['auto_record']:cancel.set();return
                    if shutil.disk_usage(directory).free<1024**3:raise RuntimeError('LIVE остановлен: свободно меньше 1 ГБ')
                    windows.pump()
                except Exception as exc:errors.append(exc);cancel.set();return
        watcher=threading.Thread(target=watch,daemon=True);watcher.start()
        try:
            quality={'720p':'720p60,720p,480p,best','1080p':'1080p60,1080p,720p,best','best':'best'}[meta['quality']]
            self.runner.log(job_id,'LIVE: непрерывное подключение; сегменты около 2 минут; CPU Whisper и тёплая Bonsai')
            try:
                self.runner.execute(['docker','compose','--profile','recorder','run','--rm','-T','--name',container,
                    'live-recorder','/recordings/'+job_id,meta['login'],quality],job_id,cancel,timeout=86400)
            except Cancelled:pass
            finally:
                done.set();watcher.join(timeout=130)
                subprocess.run(['docker','stop','--time','10',container],capture_output=True,timeout=25)
            if watcher.is_alive():raise RuntimeError('Не удалось завершить сборку live-окна; исходные части сохранены')
            if errors:raise errors[0]
            windows.pump(final=True)
            parts=closed_parts(directory)
            self.store.update_job(job_id,status='done' if parts else 'cancelled',finished=time.time(),detail=f'LIVE запись завершена · {len(parts)} частей; анализ продолжается в очереди')
        except Exception as exc:
            if done.is_set() and not watcher.is_alive():
                try:windows.pump(final=True)
                except Exception as recovery_error:self.runner.log(job_id,'Закрытые части сохранены, обработка хвоста не завершена: '+str(recovery_error),'warning')
            self.store.update_job(job_id,status='error',finished=time.time(),error=str(exc),detail='LIVE прерван; закрытые части сохранены')
            self.runner.log(job_id,str(exc),'error')
        finally:
            done.set()
            self.recordings.pop(job_id,None);self.capture_threads.pop(job_id,None)

    def poll(self):
        streamers = [s for s in self.store.streamers() if s['enabled']]
        if not streamers or not self.client.configured():
            return
        logins = [s['login'] for s in streamers]
        users = self.client.get('users', [('login', name) for name in logins])
        by_login = {u['login'].lower(): u for u in users}
        streams = self.client.get('streams', [('first', '100')]+[('user_login', name) for name in logins])
        live = {s['user_login'].lower(): s for s in streams}
        now = time.time()
        for streamer in streamers:
            user = by_login.get(streamer['login'])
            stream = live.get(streamer['login'])
            status = 'not_found' if not user else 'live' if stream else 'offline'
            self.store.update_streamer(streamer['id'], status=status, checked=now, error=None,
                                       display_name=user['display_name'] if user else streamer['login'],
                                       title=stream['title'] if stream else '', stream_id=stream['id'] if stream else None,
                                       viewers=stream['viewer_count'] if stream else None)
            if stream and streamer['auto_record']:
                updated = next(s for s in self.store.streamers() if s['id'] == streamer['id'])
                self.record(updated)
        self.last_check = now
        self.error = None

    def loop(self):
        while not self.stopping.is_set():
            try:
                self.poll()
            except Exception as exc:
                message = str(exc)[:500]
                if message != self.error:
                    self.store.log('Мониторинг Twitch: '+message, 'warning')
                self.error = message
            self.wake.wait(self.store.setting('poll_interval', 30))
            self.wake.clear()
