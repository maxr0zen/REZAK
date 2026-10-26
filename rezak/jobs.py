"""Host-side queue. GPU stages remain in their existing Docker containers."""
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from .media import ffmpeg, probe


class Cancelled(RuntimeError):
    pass


class JobRunner:
    def __init__(self, store, root):
        self.store = store
        self.root = Path(root).resolve()
        self.data = self.root/'data'
        self.stopping = threading.Event()
        self.cancellations = {}
        self.owners = set()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.loop, name='rezak-queue', daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        for event in list(self.cancellations.values()):
            event.set()
        if self.thread:
            self.thread.join(timeout=20)

    def cancel(self, job_id):
        job = self.store.job(job_id)
        if not job:
            return
        if job['status'] == 'queued':
            self.store.update_job(job_id, status='cancelled', finished=time.time(), detail='Задача отменена')
        elif job_id in self.cancellations:
            self.cancellations[job_id].set()

    def log(self, job_id, message, level='info'):
        # Secret values never enter the pipeline; still redact configured API credentials.
        message = re.sub(r'\[[0-?]*[ -/]*[@-~]', '', str(message))
        client_id = self.store.setting('twitch_client_id', '')
        if client_id:
            message = str(message).replace(client_id, '[client-id]')
        self.store.log(message, level, job_id)
        log_path = self.store.directory/'logs'/f'{job_id}.log'
        log_path.parent.mkdir(exist_ok=True)
        if log_path.exists() and log_path.stat().st_size > 10*1024*1024:
            log_path.replace(log_path.with_suffix('.previous.log'))
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(f'{time.time():.3f} {level.upper()} {str(message)[-4000:]}\n')

    def execute(self, args, job_id, cancel, timeout=86400, env=None, progress=None):
        process = subprocess.Popen([str(a) for a in args], cwd=self.root, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace',
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
        messages = queue.Queue(maxsize=256)

        def drain():
            try:
                for line in iter(process.stdout.readline, ''):
                    messages.put(line.rstrip()[-8000:])
            finally:
                messages.put(None)

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        deadline = time.monotonic()+timeout
        ended = False
        try:
            while not ended or process.poll() is None:
                if cancel.is_set() or self.stopping.is_set():
                    raise Cancelled('Задача отменена. Исходник и готовые артефакты сохранены.')
                if time.monotonic() > deadline:
                    raise RuntimeError('Превышено время ожидания операции')
                try:
                    line = messages.get(timeout=.25)
                except queue.Empty:
                    continue
                if line is None:
                    ended = True
                elif line:
                    if line.startswith('[REZAK_EVENT]'):
                        try:
                            event = json.loads(line[len('[REZAK_EVENT]'):])
                            if event.get('pipeline_owned'):
                                self.owners.add(job_id)
                            self.store.event(job_id, event)
                            if event.get('message'):
                                self.log(job_id, event['message'])
                        except (ValueError, TypeError):
                            self.log(job_id, 'Невалидное событие прогресса', 'warning')
                    elif progress and line.startswith('out_time_us='):
                        try:
                            progress(int(line.split('=', 1)[1])/1000000)
                        except ValueError:
                            pass
                    elif not progress or not line.startswith(('frame=', 'fps=', 'bitrate=', 'total_size=', 'out_time_', 'dup_frames=', 'drop_frames=', 'speed=', 'progress=', 'stream_')):
                        self.log(job_id, line, 'error' if 'Traceback' in line or 'Ошибка:' in line else 'info')
            if process.returncode:
                raise RuntimeError(f'Операция завершилась с кодом {process.returncode}. Подробности — в журнале.')
        except BaseException:
            if process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=15)
                else:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
            raise
        finally:
            process.stdout.close()

    def cleanup_gpu(self, job_id):
        names = [f'rezak-asr-{job_id}', f'rezak-asr-setup-{job_id}',f'rezak-analysis-{job_id}',f'rezak-refine-{job_id}']
        if job_id in self.owners:
            names.append('rezak-bonsai-1')
        try:
            subprocess.run(['docker', 'stop', '--time', '5', *names], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            self.log(job_id, 'Не удалось подтвердить остановку Docker. Проверьте контейнеры.', 'warning')
        self.owners.discard(job_id)

    def prepare(self, job, cancel):
        source = Path(job['input_path']).resolve()
        if not source.is_relative_to(self.data) or not source.is_file():
            raise ValueError('Исходник отсутствует в хранилище приложения')
        info = probe(source)
        streams = info['streams']
        if not any(s['codec_type'] == 'video' for s in streams) or not any(s['codec_type'] == 'audio' for s in streams):
            raise ValueError('Нужна запись с видео и аудиодорожкой')
        duration = float(info['format']['duration'])
        target = self.data/'sources'/f"{job['source_id']}.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        if source != target and not target.exists():
            if shutil.disk_usage(self.data).free < source.stat().st_size+512*1024*1024:
                raise ValueError('Недостаточно свободного места для подготовки записи')
            temporary = target.with_suffix('.preparing.mp4')
            self.store.event(job['id'], {'stage': 'prepare', 'progress': .2, 'message': 'Проверка медиа пройдена. Подготовка MP4.'})
            def progress(seconds):
                self.store.event(job['id'], {'stage': 'prepare', 'progress': min(.9, .2+.7*seconds/max(1, duration)),
                                            'message': 'Подготовка исходного файла', 'processed_ms': round(seconds*1000), 'total_ms': round(duration*1000)})
            common = [ffmpeg(), '-v', 'error', '-nostdin', '-y', '-i', source, '-map', '0:v:0', '-map', '0:a:0']
            try:
                self.execute([*common, '-c', 'copy', '-movflags', '+faststart', '-progress', 'pipe:1', temporary], job['id'], cancel, progress=progress)
            except RuntimeError as exc:
                if isinstance(exc, Cancelled):
                    raise
                self.log(job['id'], 'Контейнер требует перекодирования: пробую H.264/AAC', 'warning')
                self.execute([*common, '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-c:a', 'aac', '-progress', 'pipe:1', temporary], job['id'], cancel, progress=progress)
            probe(temporary)
            temporary.replace(target)
        self.store.update_job(job['id'], metadata={**job['metadata'], 'duration_ms': round(duration*1000), 'bytes': source.stat().st_size})
        self.store.event(job['id'], {'stage': 'prepare', 'progress': .9, 'message': 'Исходник проверен. Подключение Docker.'})

    def process_refinement(self,job,cancel,started):
        directory=self.data/'app/edits';directory.mkdir(parents=True,exist_ok=True)
        request={'job_id':job['id'],'filename':job['metadata']['parent_clip'],'title':job['title'],
                 'plan':job['metadata']['edit_plan'],'instruction':job['metadata']['instruction']}
        (directory/(job['id']+'.json')).write_text(json.dumps(request,ensure_ascii=False),encoding='utf-8')
        env={**os.environ,'REZAK_PROGRESS':'1','REZAK_JOB_ID':job['id'],'PYTHONIOENCODING':'utf-8','NO_COLOR':'1'}
        self.execute(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',self.root/'scripts/refine-clip.ps1','-JobId',job['id']],job['id'],cancel,env=env)
        outputs=[p.name for p in (self.data/'exports').glob(job['source_id']+'-*.mp4') if p.stat().st_mtime>=started-1 and p.with_suffix('.edit.json').exists() and json.loads(p.with_suffix('.edit.json').read_text(encoding='utf-8')).get('instruction')==request['instruction']]
        if not outputs:raise ValueError('Доработка не создала проверенную копию')
        self.store.update_job(job['id'],status='done',progress=100,finished=time.time(),exports=outputs,detail='Копия по вашему заданию готова')
        self.log(job['id'],'Доработка по заданию завершена','success')

    def process_edit(self,job,cancel):
        from .plan import EditPlan
        from .render import render
        from .clips import ClipLibrary
        plan=EditPlan.model_validate(job['metadata']['edit_plan'])
        self.store.event(job['id'],{'stage':'render','progress':0,'message':'Повторный монтаж по выбранным границам; нейросети не запускаются'})
        # Progress events are intercepted locally rather than written only to stdout.
        from .events import progress_sink
        token=progress_sink.set(lambda event:self.store.event(job['id'],event))
        try:
            if job['metadata'].get('auto_focus'):
                from .framing import auto_frame
                from .media import source_path
                plan=auto_frame(plan,source_path(self.data,plan.source_id),job['metadata']['auto_focus'])
            output=render(plan,self.data,cancel=cancel)
        finally:
            progress_sink.reset(token)
        library=ClipLibrary(self.data)
        try:parent=library.metadata(library.path(job['metadata']['parent_clip']))
        except FileNotFoundError:parent={}
        library.write_metadata(output,{**library.metadata(output),**({'publisher_streamer_id':parent['publisher_streamer_id']} if parent.get('publisher_streamer_id') else {}),'title':job['title'],'parent_clip':job['metadata']['parent_clip']})
        self.store.event(job['id'],{'stage':'verify','progress':1,'message':'Новая копия проверена'})
        self.store.update_job(job['id'],status='done',progress=100,finished=time.time(),exports=[output.name],detail='Отредактированная копия готова')
        self.log(job['id'],'Отредактированная копия готова: '+output.name,'success')

    def process(self, job):
        job_id = job['id']
        cancel = self.cancellations.setdefault(job_id, threading.Event())
        started = time.time()
        self.store.update_job(job_id, status='running', started=started, error=None, detail='Проверка исходника')
        self.log(job_id, f"Начало обработки: {job['title']}")
        try:
            if job['kind']=='clip_refine':
                self.process_refinement(job,cancel,started)
                return
            if job['kind']=='clip_edit':
                self.process_edit(job,cancel)
                return
            self.prepare(job, cancel)
            if 'adhd_mode' in job['metadata']:
                presentation=self.data/'sources'/(job['source_id']+'.presentation.json')
                temporary=presentation.with_suffix('.tmp')
                temporary.write_text(json.dumps({'adhd_mode':bool(job['metadata']['adhd_mode'])}),encoding='utf-8')
                temporary.replace(presentation)
            env = {**os.environ, 'REZAK_PROGRESS': '1', 'REZAK_JOB_ID': job_id, 'PYTHONIOENCODING': 'utf-8', 'COMPOSE_ANSI': 'never', 'NO_COLOR': '1'}
            command=['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                          self.root/'scripts/process-stream.ps1', '-SourceId', job['source_id'],
                          '-OutputProfile', job['profile']]
            if job['metadata'].get('operation')=='shorts':command.append('-ReselectShorts')
            if job['metadata'].get('operation')=='live':
                command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',self.root/'scripts/process-live.ps1',
                         '-SourceId',job['source_id'],'-RequestFile',job['metadata']['live_request']]
            if job['metadata'].get('operation')=='curate':
                edits=self.data/'app/edits';edits.mkdir(parents=True,exist_ok=True)
                (edits/(job_id+'.json')).write_text(json.dumps({**job['metadata'],'job_id':job_id,'title':job['title']},ensure_ascii=False),encoding='utf-8')
                command+=['-CurateRequest',job_id]
            self.execute(command, job_id, cancel, env=env)
            exports = [p.name for p in (self.data/'exports').glob(job['source_id']+'-*.mp4')
                       if p.stat().st_mtime >= started-1 and p.with_suffix('.probe.json').exists()]
            owner=job['metadata'].get('streamer_id')
            parent=self.store.job(job['metadata'].get('recording_job') or job['metadata'].get('live_session') or '')
            if not owner and parent:owner=parent['metadata'].get('streamer_id')
            if owner:
                from .clips import ClipLibrary
                library=ClipLibrary(self.data)
                for name in exports:
                    output=library.path(name);library.write_metadata(output,{**library.metadata(output),'publisher_streamer_id':owner})
            message = f'Готово: {len(exports)} роликов' if exports else 'Подходящих законченных эпизодов не найдено'
            self.store.update_job(job_id, status='done', progress=100, finished=time.time(), exports=exports, detail=message)
            self.log(job_id, message, 'success')
        except Cancelled as exc:
            self.cleanup_gpu(job_id)
            self.store.update_job(job_id, status='cancelled', finished=time.time(), detail=str(exc))
            self.log(job_id, str(exc), 'warning')
        except Exception as exc:
            self.cleanup_gpu(job_id)
            self.store.update_job(job_id, status='error', finished=time.time(), error=str(exc), detail=str(exc))
            self.log(job_id, str(exc), 'error')
        finally:
            self.owners.discard(job_id)
            self.cancellations.pop(job_id, None)

    def loop(self):
        while not self.stopping.wait(.6):
            rows = self.store.rows("SELECT id FROM jobs WHERE status='queued' AND kind IN ('video','clip_edit','clip_refine') ORDER BY created LIMIT 1")
            if rows and not self.store.setting('queue_paused', False):
                self.process(self.store.job(rows[0]['id']))
