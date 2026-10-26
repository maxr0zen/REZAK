"""Local, attributed secondary footage. No network activity during rendering."""
import hashlib
import json
from pathlib import Path


def select_background(plan, root):
    if plan.profile != 'vertical':
        return None
    presentation=Path(root)/'sources'/(plan.source_id+'.presentation.json')
    if presentation.is_file() and not json.loads(presentation.read_text(encoding='utf-8')).get('adhd_mode',False):
        return None
    directory = (Path(root) / 'backgrounds').resolve()
    manifest = directory / 'library.json'
    if not manifest.is_file():
        return None
    config = json.loads(manifest.read_text(encoding='utf-8'))
    if not config.get('enabled', False):
        return None
    candidates = []
    import re
    for item in config.get('assets', []):
        name = item.get('file', '')
        if not re.fullmatch(r'[a-zA-Z0-9_-]+\.(mp4|webm|mkv)', name):
            raise ValueError('Недопустимое имя фонового видео')
        path = directory / name
        if path.is_symlink() or path.resolve().parent != directory:
            raise ValueError('Фоновое видео находится вне библиотеки')
        if path.is_file():
            if not item.get('source_url') or not item.get('license'):
                raise ValueError('Для фонового видео укажите источник и лицензию')
            candidates.append((path, item))
    if not candidates:
        raise ValueError('Нет доступных фоновых видео в data/backgrounds/library.json')
    identity = f'{plan.source_id}:{plan.segments[0].start_ms}'
    seed = int(hashlib.sha256(identity.encode()).hexdigest()[:8], 16)
    path, credit = candidates[seed % len(candidates)]
    return path, credit, seed


def stack_layout(segment, width, height, sw, sh):
    """Fixed panels: headlines are overlays and never reserve layout space."""
    header = 0
    if segment.framing == 'split':
        content = round(height * .50 / 2) * 2
        gap = 0  # Split compositions already reserve their caption band.
    else:
        region = segment.region if segment.framing == 'crop' else None
        natural = width * (sh * region.h if region else sh) / (sw * region.w if region else sw)
        content = max(2, min(round(height * .375 / 2) * 2, round(natural / 2) * 2))
        gap = round(height * .069 / 2) * 2
    bottom_y = header + content + gap
    return header, content, gap, bottom_y, height - bottom_y


def stack_filter(label, out, segment, width, height, sw, sh, headline_ms=0):
    from .framing import video_filter
    header, content, gap, bottom_y, _ = stack_layout(segment, width, height, sw, sh)
    filters = video_filter(label, out + 'primary', segment, width, content, sw, sh)
    duration=(segment.end_ms-segment.start_ms)/1000
    filters += [f'color=c=black:s={width}x{height}:r=30:d={duration+.1}[{out}canvas]',
                f"[{out}canvas][{out}primary]overlay=0:0:shortest=1[{out}]"]
    return filters
