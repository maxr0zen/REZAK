"""Local desktop UI/API. Run on loopback with one Uvicorn worker."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
import httpx
from typing import Literal
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.responses import Response
from .plan import Region
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .clips import ClipLibrary
from .jobs import JobRunner
from .media import ffmpeg
from .store import STAGES, Store
from .twitch import TwitchMonitor, protect

STATIC = Path(__file__).parent/'static'
MAX_UPLOAD = 20*1024**3


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class StreamerInput(Input):
    login: str
    auto_record: bool = True
    auto_clip: bool = True
    live_clip: bool = False
    adhd_mode: bool = False
    quality: Literal['720p', '1080p', 'best'] = '720p'

    @field_validator('login')
    @classmethod
    def normalize(cls, value):
        value = value.strip().lower().rstrip('/')
        value = re.sub(r'^https?://(?:www\.)?twitch\.tv/', '', value).lstrip('@')
        if not re.fullmatch(r'[a-z0-9_]{1,25}', value):
            raise ValueError('Введите логин или ссылку вида twitch.tv/channel')
        return value


class StreamerPatch(Input):
    enabled: bool | None = None
    auto_record: bool | None = None
    auto_clip: bool | None = None
    live_clip: bool | None = None
    adhd_mode: bool | None = None
    quality: Literal['720p', '1080p', 'best'] | None = None


class SettingsInput(Input):
    client_id: str = Field(max_length=128)
    client_secret: str = Field(default='', max_length=512)
    poll_interval: int = Field(default=30, ge=30, le=300)
    verify: bool = True


class PauseInput(Input):
    paused: bool


class ClipTitle(Input):
    title: str = Field(min_length=1,max_length=240)

    @field_validator('title')
    @classmethod
    def clean_title(cls,value):
        value=value.strip()
        if not value or any(ord(c)<32 for c in value):raise ValueError('Укажите название без управляющих символов')
        return value

class ClipPrompt(ClipTitle):
    instruction: str = Field(min_length=3,max_length=1500)

class ClipTrim(ClipTitle):
    start_ms: int = Field(ge=0,strict=True)
    end_ms: int = Field(gt=0,strict=True)

class ClipBatch(BaseModel):
    filenames: list[str] = Field(min_length=1,max_length=100)

class ClipFraming(ClipTitle):
    mode: Literal['auto','fit','crop','split']
    focus: Literal['speaker','screen','reaction']='speaker'
    region: Region | None = None
    secondary_region: Region | None = None


def configure_tools(root):
    if not os.environ.get('FFMPEG') and not shutil.which('ffmpeg'):
        try:
            import imageio_ffmpeg
            os.environ['FFMPEG'] = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pass
    if not os.environ.get('FFPROBE') and not shutil.which('ffprobe') and (root/'.tools/ffprobe.exe').exists():
        os.environ['FFPROBE'] = str(root/'.tools/ffprobe.exe')


def create_app(root=None, start_background=True, testing=False):
    root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    data = root/'data'
    for name in ('app/temp', 'imports', 'sources', 'exports', 'recordings', 'app/covers'):
        (data/name).mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(data/'app/temp')
    configure_tools(root)
    store = Store(data/'app')
    runner = JobRunner(store, root)
    library = ClipLibrary(data)
    monitor = TwitchMonitor(store, runner)
    from .publishing import Publishing
    publishing=Publishing(store,data)
    system = {'docker': None, 'gpu': None, 'model': 'unknown', 'updated': None}
    system_stop = threading.Event()
    server_lock = None

    def update_system():
        while not system_stop.is_set():
            try:
                result = subprocess.run(['docker', 'info', '--format', '{{.ServerVersion}}'], capture_output=True, text=True, timeout=5)
                system['docker'] = result.stdout.strip() if result.returncode == 0 else False
                if system['docker']:
                    model = subprocess.run(['docker', 'inspect', '--format', '{{.State.Status}}', 'rezak-bonsai-1'], capture_output=True, text=True, timeout=5)
                    system['model'] = model.stdout.strip() if model.returncode == 0 else 'not_created'
            except (OSError, subprocess.TimeoutExpired):
                system['docker'] = False
            try:
                result = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.used,memory.total', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    name, used, total = [s.strip() for s in result.stdout.splitlines()[0].split(',')]
                    system['gpu'] = {'name': name.replace('NVIDIA GeForce ', ''), 'used_mib': int(used), 'total_mib': int(total)}
            except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
                system['gpu'] = None
            system['updated'] = time.time()
            system_stop.wait(20)

    @asynccontextmanager
    async def lifespan(app):
        nonlocal server_lock
        if start_background:
            # A single host manager owns the SQLite queue and the GPU pipeline.
            server_lock = (data/'app/studio.lock').open('a+b')
            if os.name == 'nt':
                import msvcrt
                server_lock.seek(0)
                server_lock.write(b'0')
                server_lock.flush()
                server_lock.seek(0)
                try:
                    msvcrt.locking(server_lock.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    server_lock.close()
                    raise RuntimeError('Студия уже запущена. Откройте существующее окно.')
            for job in store.jobs():
                if job['kind'] == 'capture' and job['status'] == 'recording':
                    try:
                        subprocess.run(['docker', 'stop', '--time', '5', 'rezak-record-'+job['id']], capture_output=True, timeout=20)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            store.recover()
            store.log('Студия запущена. История и очередь загружены из SQLite.', 'success')
            runner.start()
            monitor.start()
            publishing.start()
            threading.Thread(target=update_system, daemon=True, name='system-monitor').start()
        try:
            yield
        finally:
            publishing.stop()
            system_stop.set()
            runner.stopping.set()
            monitor.stop()
            runner.stop()
            if server_lock:
                server_lock.close()

    app = FastAPI(title='Rezak Studio', lifespan=lifespan)
    app.state.store = store
    app.state.runner = runner
    app.state.monitor = monitor
    app.state.publishing = publishing
    from .publishing_api import router as publishing_router
    app.include_router(publishing_router(publishing))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost']+(['testserver'] if testing else []))

    @app.middleware('http')
    async def local_requests(request, call_next):
        if request.url.path.startswith('/api/') and request.method not in ('GET', 'HEAD'):
            if request.headers.get('x-rezak-client') != '1':
                return JSONResponse({'detail': 'Операция доступна из локального приложения'}, 403)
            origin = request.headers.get('origin')
            if origin and origin != f'{request.url.scheme}://{request.headers.get("host")}':
                return JSONResponse({'detail': 'Недопустимый источник запроса'}, 403)
        if request.url.path == '/api/uploads':
            try:
                if int(request.headers.get('content-length', 0)) > MAX_UPLOAD+1024*1024:
                    return JSONResponse({'detail': 'Максимальный размер записи — 20 ГБ'}, 413)
            except ValueError:
                return JSONResponse({'detail': 'Некорректный размер запроса'}, 400)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; style-src 'self'; font-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    def get_job(job_id):
        job = store.job(job_id)
        if not job:
            raise HTTPException(404, 'Задача не найдена')
        return job

    def safe_export(filename):
        if Path(filename).name != filename or not re.fullmatch(r'[a-zA-Z0-9_-]+\.mp4', filename):
            raise HTTPException(404, 'Ролик не найден')
        path = (data/'exports'/filename).resolve()
        if not path.is_relative_to((data/'exports').resolve()) or not path.is_file():
            raise HTTPException(404, 'Ролик не найден')
        return path

    def clips():
        result = []
        seen = set()
        titles = {j['source_id']: j['title'] for j in store.rows('SELECT source_id,title FROM jobs WHERE kind=\'video\'')}
        for path in sorted((data/'exports').glob('*.mp4'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                plan = json.loads(path.with_suffix('.plan.json').read_text(encoding='utf-8'))
                info = json.loads(path.with_suffix('.probe.json').read_text(encoding='utf-8'))
                identity = library.plan_identity(plan)
                if identity in seen:
                    continue
                seen.add(identity)
                video = next(s for s in info['streams'] if s['codec_type'] == 'video')
                custom=library.metadata(path)
                if custom.get('superseded_by'):
                    try:library.path(custom['superseded_by']);continue
                    except FileNotFoundError:pass
                result.append({'filename': path.name, 'source_id': plan['source_id'], 'profile': plan['profile'],
                               'editable_duration_ms':sum(x['end_ms']-x['start_ms'] for x in plan['segments']),
                               'title': custom.get('title') or plan.get('title') or titles.get(plan['source_id'], 'Тестовая запись' if plan['source_id'].startswith(('smoke', 'synthetic')) else plan['source_id']),
                               'duration_ms': round(float(info['format']['duration'])*1000), 'width': video['width'],
                               'height': video['height'], 'created': path.stat().st_mtime, 'bytes': path.stat().st_size,
                               'test_fixture': plan['source_id'].startswith(('smoke', 'synthetic'))})
            except (OSError, ValueError, KeyError, StopIteration):
                continue
            if len(result) == 100:
                break
        return result

    @app.get('/api/status')
    def status():
        jobs = store.jobs()
        return {'application': 'rezak-studio', 'version': '0.2.0', 'jobs': jobs, 'streamers': store.streamers(),
                'clips': clips(), 'publishing':publishing.snapshot(), 'stages': [{'id': key, 'label': label, 'weight': weight} for key, label, weight in STAGES],
                'system': {**system, 'free_bytes': shutil.disk_usage(data).free},
                'queue_paused': store.setting('queue_paused', False),
                'twitch': {'configured': monitor.client.configured(), 'last_check': monitor.last_check,
                           'error': monitor.error, 'poll_interval': store.setting('poll_interval', 30)}}

    @app.get('/api/logs')
    def logs(job_id: str | None = None, after: int = 0):
        if job_id:
            get_job(job_id)
        return store.logs(job_id, after)

    @app.get('/api/jobs/{job_id}/log')
    def download_log(job_id: str):
        get_job(job_id)
        path = data/'app/logs'/f'{job_id}.log'
        if not path.exists():
            path.parent.mkdir(exist_ok=True)
            path.write_text('\n'.join(f"{row['at']:.3f} {row['level'].upper()} {row['message']}" for row in store.logs(job_id, limit=2000)), encoding='utf-8')
        return FileResponse(path, media_type='text/plain; charset=utf-8', filename=f'rezak-{job_id[:8]}.log')

    @app.post('/api/uploads')
    async def upload(file: UploadFile = File(...), profile: Literal['both', 'vertical', 'horizontal'] = Form('both')):
        original = Path((file.filename or 'video').replace('\\', '/')).name
        suffix = Path(original).suffix.lower()
        if suffix not in ('.mp4', '.mkv', '.mov', '.webm', '.ts', '.m4v'):
            raise HTTPException(400, 'Поддерживаются MP4, MKV, MOV, WEBM, TS и M4V')
        source_id = 'upload_'+uuid.uuid4().hex
        path = data/'imports'/(source_id+suffix)
        temporary = path.with_suffix(suffix+'.upload')
        total = 0
        try:
            with temporary.open('xb') as output:
                while chunk := await file.read(4*1024*1024):
                    total += len(chunk)
                    if total > MAX_UPLOAD:
                        raise HTTPException(413, 'Максимальный размер записи — 20 ГБ')
                    if shutil.disk_usage(data).free < len(chunk)+512*1024*1024:
                        raise HTTPException(507, 'Недостаточно места на диске')
                    output.write(chunk)
            if total == 0:
                raise HTTPException(400, 'Файл пустой')
            temporary.replace(path)
        finally:
            await file.close()
            if temporary.exists():
                temporary.unlink()
        return store.create_job(original[:240], source_id, input_path=path, profile=profile, metadata={'bytes': total, 'original_name': original[:240]})

    @app.post('/api/queue')
    def queue_state(value: PauseInput):
        store.set_setting('queue_paused', value.paused)
        store.log('Очередь приостановлена' if value.paused else 'Очередь возобновлена')
        return {'paused': value.paused}

    @app.post('/api/jobs/{job_id}/cancel')
    def cancel_job(job_id: str):
        job = get_job(job_id)
        if job['status'] not in ('queued', 'running', 'recording'):
            raise HTTPException(409, 'Задача уже завершена')
        monitor.cancel(job_id) if job['kind'] == 'capture' else runner.cancel(job_id)
        return {'requested': True}

    @app.post('/api/jobs/{job_id}/retry')
    def retry_job(job_id: str):
        job = get_job(job_id)
        if job['kind'] not in ('video','clip_edit','clip_refine') or job['status'] not in ('error', 'cancelled', 'interrupted'):
            raise HTTPException(409, 'Для этой задачи повторный запуск недоступен')
        store.update_job(job_id, status='queued', progress=0, stages={}, error=None, detail='Повторный запуск в очереди', finished=None)
        store.log('Запрошен повторный запуск; готовые артефакты будут использованы из кеша', job_id=job_id)
        return store.job(job_id)

    @app.post('/api/jobs/{job_id}/recover')
    def recover_capture(job_id: str):
        job = get_job(job_id)
        if job['kind'] != 'capture' or job['status'] in ('queued', 'recording'):
            raise HTTPException(409, 'Сначала остановите запись')
        if job['metadata'].get('live_mode'):
            from .live import LiveWindows
            LiveWindows(monitor,job_id,data/'recordings'/job_id).pump(final=True)
            return {'jobs':[j for j in store.jobs() if j['metadata'].get('live_session')==job_id]}
        recovered = []
        for part in (data/'recordings'/job_id).glob('*.ts'):
            dedupe = 'recover:'+job_id+':'+part.name
            if part.stat().st_size and not store.rows('SELECT id FROM jobs WHERE dedupe=?', (dedupe,)):
                recovered.append(store.create_job('Восстановленная запись · '+part.name, 'recovered_'+uuid.uuid4().hex,
                                                  input_path=part, dedupe=dedupe, metadata={'recording_job': job_id,'adhd_mode':bool(job['metadata'].get('adhd_mode',False))}))
        return {'jobs': recovered}

    @app.post('/api/streamers')
    def add_streamer(value: StreamerInput):
        if len(store.streamers()) >= 100:
            raise HTTPException(400, 'Можно отслеживать до 100 стримеров')
        try:
            row = store.add_streamer(**value.model_dump())
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Этот стример уже добавлен')
        store.log('Добавлен Twitch-канал '+row['login'])
        monitor.wake.set()
        return row

    @app.patch('/api/streamers/{streamer_id}')
    def patch_streamer(streamer_id: str, value: StreamerPatch):
        if not any(s['id'] == streamer_id for s in store.streamers()):
            raise HTTPException(404, 'Стример не найден')
        if value.live_clip is not None and any(j['kind']=='capture' and j['status']=='recording' and j['metadata'].get('streamer_id')==streamer_id for j in store.jobs()):
            raise HTTPException(409,'Сначала остановите текущую запись, затем измените LIVE-режим')
        fields = value.model_dump(exclude_none=True)
        if fields:
            store.update_streamer(streamer_id, **fields)
        if fields.get('enabled') is False or fields.get('auto_record') is False:
            monitor.stop_streamer(streamer_id)
        monitor.wake.set()
        return {'ok': True}

    @app.delete('/api/streamers/{streamer_id}')
    def delete_streamer(streamer_id: str):
        monitor.stop_streamer(streamer_id)
        store.execute("UPDATE publishing_jobs SET status=CASE WHEN status='queued' THEN 'cancelled' ELSE 'cancel_requested' END WHERE streamer_id=? AND status IN ('queued','uploading')",(streamer_id,))
        store.execute('DELETE FROM publishing_routes WHERE streamer_id=?',(streamer_id,))
        store.execute('DELETE FROM streamers WHERE id=?', (streamer_id,))
        return {'ok': True}

    @app.post('/api/streamers/{streamer_id}/record')
    def record_streamer(streamer_id: str):
        row = next((s for s in store.streamers() if s['id'] == streamer_id), None)
        if not row:
            raise HTTPException(404, 'Стример не найден')
        try:
            return monitor.record(row, force=True)
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.post('/api/twitch/refresh')
    def refresh_twitch():
        monitor.wake.set()
        return {'requested': True, 'configured': monitor.client.configured()}

    @app.get('/api/settings')
    def settings():
        return {'client_id': store.setting('twitch_client_id', ''), 'secret_saved': bool(store.setting('twitch_secret')),
                'poll_interval': store.setting('poll_interval', 30), 'data_directory': str(data),
                'max_upload_gb': 20, 'asr': 'Whisper small · int8_float16', 'llm': 'Bonsai2 27B · PTQ1_0'}

    @app.post('/api/settings')
    def save_settings(value: SettingsInput):
        if not re.fullmatch(r'[a-zA-Z0-9]{1,128}', value.client_id):
            raise HTTPException(400, 'Укажите Twitch Client ID из консоли разработчика')
        encrypted_secret = protect(value.client_secret) if value.client_secret else store.setting('twitch_secret')
        if not encrypted_secret:
            raise HTTPException(400, 'Укажите Twitch Client Secret')
        if value.verify:
            try:
                response = httpx.post('https://id.twitch.tv/oauth2/token', data={
                    'client_id': value.client_id, 'client_secret': protect(encrypted_secret, decrypt=True),
                    'grant_type': 'client_credentials'}, timeout=15)
                if response.status_code != 200:
                    raise HTTPException(400, 'Twitch отклонил ключи. Проверьте Client ID и Client Secret.')
            except httpx.HTTPError:
                raise HTTPException(400, 'Не удалось связаться с Twitch. Проверьте интернет и повторите.')
        store.set_setting('twitch_secret', encrypted_secret)
        store.set_setting('twitch_client_id', value.client_id)
        store.set_setting('poll_interval', value.poll_interval)
        monitor.client.token = None
        store.log('Настройки Twitch сохранены'+(' и проверены' if value.verify else ''))
        monitor.wake.set()
        return {'ok': True, 'verified': value.verify}

    @app.post('/api/open-exports')
    def open_exports():
        if os.name != 'nt':
            raise HTTPException(409, 'Откройте каталог data/exports вручную')
        os.startfile(str(data/'exports'))
        return {'ok': True}

    @app.post('/api/shutdown')
    async def shutdown():
        callback = getattr(app.state, 'shutdown', None)
        if not callback:
            raise HTTPException(409, 'Остановите сервер в терминале')
        asyncio.get_running_loop().call_later(.3, callback)
        return {'ok': True}

    def clip_operation(operation):
        try:return operation()
        except FileNotFoundError as exc:raise HTTPException(404,str(exc))
        except (ValueError,KeyError) as exc:raise HTTPException(400,str(exc))
        except OSError:raise HTTPException(409,'Файл занят или недоступен. Закройте проигрыватель и повторите.')

    @app.patch('/api/clips/{filename}')
    def rename_clip(filename: str,value: ClipTitle):
        result=clip_operation(lambda:library.rename(filename,value.title))
        store.log('Изменено название ролика '+filename)
        return result

    @app.post('/api/clips/{filename}/trim')
    def trim_clip(filename: str,value: ClipTrim):
        plan=clip_operation(lambda:library.trimmed_plan(filename,value.start_ms,value.end_ms))
        source=data/'sources'/(plan.source_id+'.mp4')
        if not source.is_file():raise HTTPException(409,'Исходная запись отсутствует: повторный монтаж недоступен')
        return store.create_job(value.title,plan.source_id,input_path=source,profile=plan.profile,kind='clip_edit',
                                metadata={'edit_plan':plan.model_dump(),'parent_clip':filename,
                                          'duration_ms':value.end_ms-value.start_ms})

    @app.post('/api/clips/{filename}/refine')
    def refine_clip(filename: str,value: ClipPrompt):
        path=clip_operation(lambda:library.path(filename))
        from .plan import EditPlan
        plan=clip_operation(lambda:EditPlan.model_validate_json(path.with_suffix('.plan.json').read_text(encoding='utf-8')))
        source=data/'sources'/(plan.source_id+'.mp4')
        if not source.is_file():raise HTTPException(409,'Исходная запись отсутствует')
        if not value.instruction.strip():raise HTTPException(400,'Напишите задание для этой нарезки')
        return store.create_job(value.title,plan.source_id,input_path=source,profile=plan.profile,kind='clip_refine',
                                metadata={'edit_plan':plan.model_dump(),'instruction':value.instruction.strip(),'parent_clip':filename})

    @app.get('/api/clips/{filename}/framing')
    def clip_framing(filename: str):
        path=clip_operation(lambda:library.path(filename))
        return json.loads(path.with_suffix('.plan.json').read_text(encoding='utf-8'))

    @app.get('/api/clips/{filename}/source-frame')
    def clip_source_frame(filename: str):
        from .framing import frame
        from .media import source_path
        import cv2
        path=clip_operation(lambda:library.path(filename))
        plan=json.loads(path.with_suffix('.plan.json').read_text(encoding='utf-8'))
        segment=plan['segments'][0]
        image=clip_operation(lambda:frame(source_path(data,plan['source_id']),(segment['start_ms']+segment['end_ms'])//2))
        ok,encoded=cv2.imencode('.jpg',image)
        if not ok:raise HTTPException(500,'Не удалось подготовить кадр')
        return Response(content=encoded.tobytes(),media_type='image/jpeg')

    @app.post('/api/clips/{filename}/framing')
    def change_framing(filename: str,value: ClipFraming):
        from .plan import EditPlan
        path=clip_operation(lambda:library.path(filename))
        plan=EditPlan.model_validate_json(path.with_suffix('.plan.json').read_text(encoding='utf-8'))
        if plan.profile!='vertical':raise HTTPException(400,'Кадрирование доступно для TikTok')
        update={'framing':'fit' if value.mode=='auto' else value.mode,'region':value.region,'secondary_region':value.secondary_region,'framing_note':'Ручное кадрирование'}
        payload=plan.model_dump();payload['title']=value.title
        payload['segments']=[{**segment.model_dump(),**update} for segment in plan.segments]
        plan=clip_operation(lambda:EditPlan.model_validate(payload))
        source=data/'sources'/(plan.source_id+'.mp4')
        if not source.is_file():raise HTTPException(409,'Исходная запись отсутствует')
        return store.create_job(value.title,plan.source_id,input_path=source,profile='vertical',kind='clip_edit',metadata={'edit_plan':plan.model_dump(),'parent_clip':filename,**({'auto_focus':value.focus} if value.mode=='auto' else {})})

    @app.post('/api/clips/delete-many')
    def delete_clips(value: ClipBatch):
        def delete():
            with store.lock:
                publishing.assert_deletable(value.filenames)
                return library.delete_many(value.filenames)
        result=clip_operation(delete)
        store.log('Ролики перемещены в корзину: '+str(result['copies']))
        return result

    @app.delete('/api/clips/{filename}')
    def delete_clip(filename: str):
        def delete():
            with store.lock:
                publishing.assert_deletable([filename])
                return library.delete(filename)
        result=clip_operation(delete)
        store.log('Ролик перемещён в корзину: '+filename)
        return result

    @app.post('/api/trash/{token}/restore')
    def restore_clip(token: str):
        return clip_operation(lambda:library.restore(token))

    @app.get('/api/clips/{filename}')
    def clip_file(filename: str, download: bool = False):
        path = safe_export(filename)
        name=None
        if download:
            from .titling import download_name
            plan=json.loads(path.with_suffix('.plan.json').read_text(encoding='utf-8'))
            title=library.metadata(path).get('title') or plan.get('title') or 'Видео'
            name=download_name(title,plan['profile'])
        return FileResponse(path, media_type='video/mp4', filename=name)

    cover_locks = {}
    cover_locks_guard = threading.Lock()

    @app.get('/api/covers/{filename}')
    def cover_file(filename: str):
        path = safe_export(filename)
        cover = data/'app/covers'/(path.stem+'.jpg')
        with cover_locks_guard:
            lock = cover_locks.setdefault(filename, threading.Lock())
        with lock:
            if not cover.exists():
                temporary = cover.with_suffix('.tmp.jpg')
                # The first frame exists even for sub-second exports.
                result = subprocess.run([ffmpeg(), '-v', 'error', '-nostdin', '-y', '-i', str(path),
                                         '-frames:v', '1', '-vf', 'scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:(ow-iw)/2:(oh-ih)/2',
                                         str(temporary)], capture_output=True, timeout=20)
                if result.returncode or not temporary.exists():
                    raise HTTPException(404, 'Превью недоступно')
                temporary.replace(cover)
        return FileResponse(cover, media_type='image/jpeg')

    app.mount('/static', StaticFiles(directory=STATIC), name='static')

    @app.get('/')
    def index():
        return FileResponse(STATIC/'react/index.html')

    return app


app = create_app()
