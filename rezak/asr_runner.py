"""Распознавание речи в GPU-контейнере и чтение готовой расшифровки.

Контейнер asr работает с файлом data/sources/<source_id>.mp4 и складывает
расшифровку в том артефактов. Студия запускает контейнер сама, чтобы
ролики по играм получали субтитры без ручного распознавания.
"""
import json
import subprocess
from pathlib import Path

# Копирует свежую расшифровку из тома артефактов на диск студии.
COPY_SCRIPT = ("from pathlib import Path; import shutil,sys; "
               "files=list(Path('/data/transcripts').glob(sys.argv[1]+'-*.json')); "
               "p=max(files,key=lambda p:p.stat().st_mtime) if files else None; "
               "p and shutil.copyfile(p,Path('/host-transcripts')/p.name)")


class AsrUnavailable(RuntimeError):
    """Распознавание речи недоступно: нет Docker или образа."""


def docker_ready(timeout=20):
    """True when the Docker daemon answers."""
    try:
        result = subprocess.run(['docker', 'info', '--format', '{{.ServerVersion}}'],
                                capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def transcript_path(root, source_id):
    """The newest transcript of the source stored on disk."""
    directory = Path(root) / 'data' / 'transcripts'
    files = sorted(directory.glob(source_id + '-*.json'), key=lambda path: path.stat().st_mtime)
    for path in reversed(files):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        # A file that is not a transcript must not be taken for one.
        if isinstance(data, dict) and 'segments' in data:
            return path
    return None


def transcribe(root, source_id, *, timeout=1800):
    """Recognize the speech of a source and return its transcript."""
    root = Path(root)
    script = root / 'docker' / 'asr' / 'asr.py'
    if not script.is_file():
        raise AsrUnavailable('Скрипт распознавания не найден: ' + str(script))
    if not docker_ready():
        raise AsrUnavailable('Docker не запущен: расшифровка речи недоступна')
    command = ['docker', 'compose', '--profile', 'asr', 'run', '--rm',
               '--name', 'rezak-asr-' + source_id,
               '-v', f'{script}:/service/asr.py:ro',
               'asr', 'transcribe', source_id]
    try:
        result = subprocess.run(command, cwd=str(root), capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AsrUnavailable('Распознавание не уложилось в отведённое время') from None
    except OSError as exc:
        raise AsrUnavailable('Не удалось запустить распознавание: ' + str(exc)) from None
    if result.returncode:
        lines = result.stderr.decode('utf-8', 'replace').strip().splitlines()
        detail = lines[-1] if lines else 'код ' + str(result.returncode)
        raise AsrUnavailable('Распознавание не удалось: ' + detail)
    transcripts = root / 'data' / 'transcripts'
    transcripts.mkdir(parents=True, exist_ok=True)
    copy = ['docker', 'compose', 'run', '--rm', '-T', '--no-deps', '--entrypoint', 'python',
            '-v', f'{transcripts}:/host-transcripts', 'app', '-c', COPY_SCRIPT, source_id]
    copied = subprocess.run(copy, cwd=str(root), capture_output=True, timeout=600)
    if copied.returncode:
        raise AsrUnavailable('Не удалось забрать расшифровку из контейнера')
    path = transcript_path(root, source_id)
    if path is None:
        raise AsrUnavailable('Расшифровка не сохранена')
    return json.loads(path.read_text(encoding='utf-8'))
