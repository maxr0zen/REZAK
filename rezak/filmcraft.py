"""Reference-style short montage rendered by the FilmCraft engine over MCP.

The engine owns the timeline: the studio cuts the webcam and the gameplay into
panels of the exact size the montage needs, FilmCraft places those panels as
clips, draws the caption words and burns the result into a 1080x1920 file.

Everything the engine does here was measured on its own renders, not guessed:
 - a clip is drawn at its native size, centred in the frame; the Motion effect
   moves it, so `position` is the point where the panel centre lands and
   `anchor` is that centre in the panel's own pixels;
 - text graphics use the bundled "Rezak Wide" face (Montserrat ExtraBold
   stretched by 1.225, which is the width of the reference face), white fill
   with a black outer stroke, centred over the panel boundary;
 - the reference caption ink is 211x53 px in a 1080x1920 frame, so the graphic
   size is 55.5 px and the baseline sits 0.3*size below the ink centre.
"""
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .tiktok import FONT_DIR, get_style

ENV_CLI = 'REZAK_FILMCRAFT'
DEFAULT_NAMES = ('filmcraft-cli.exe', 'filmcraft-cli')
WIDE_FONT = FONT_DIR / 'RezakWide-ExtraBold.ttf'
WIDE_FAMILY = 'Rezak Wide'
OUTPUT_SIZE = (1080, 1920)
OUTPUT_FPS = 30
# The engine counts time in ticks: a second is 254016000000 ticks.
TICKS_PER_SECOND = 254016000000


def cli_path(store=None):
    """Locate the FilmCraft engine: studio setting, environment, then PATH."""
    candidates = []
    if store is not None:
        try:
            configured = store.setting('filmcraft_cli', '')
        except Exception:
            configured = ''
        if configured:
            candidates.append(Path(configured))
    if os.environ.get(ENV_CLI):
        candidates.append(Path(os.environ[ENV_CLI]))
    local = Path(os.environ.get('LOCALAPPDATA', '')) / 'Rezak' / 'filmcraft'
    for name in DEFAULT_NAMES:
        candidates.append(local / name)
    for name in DEFAULT_NAMES:
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def available(store=None):
    return cli_path(store) is not None


def caption_font_installed():
    """True when the engine can see the bundled caption face."""
    if os.name != 'nt':
        return False
    fonts = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'Windows' / 'Fonts'
    return (fonts / WIDE_FONT.name).is_file()


def install_caption_font():
    """Install the bundled caption face for the current user (Windows only).

    The engine loads fonts from the operating system, so the wide face has to
    be registered there before FilmCraft can draw the captions.
    """
    if os.name != 'nt':
        raise EngineError('Установка шрифта поддерживается только в Windows')
    if not WIDE_FONT.is_file():
        raise EngineError('Не найден встроенный шрифт подписей')
    fonts = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'Windows' / 'Fonts'
    fonts.mkdir(parents=True, exist_ok=True)
    target = fonts / WIDE_FONT.name
    shutil.copy2(WIDE_FONT, target)
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                          r'Software\Microsoft\Windows NT\CurrentVersion\Fonts', 0,
                          winreg.KEY_SET_VALUE)
    try:
        winreg.SetValueEx(key, f'{WIDE_FAMILY} (TrueType)', 0, winreg.REG_SZ, str(target))
    finally:
        winreg.CloseKey(key)
    return target


class EngineError(RuntimeError):
    pass


class Session:
    """Minimal MCP client for the FilmCraft engine."""

    def __init__(self, cli, timeout=3600):
        self.cli = Path(cli)
        self.timeout = timeout
        self.proc = subprocess.Popen([str(self.cli), 'mcp'], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, encoding='utf-8', bufsize=1)
        self.lock = threading.Lock()
        self.responses = {}
        self.counter = 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.call('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                                  'clientInfo': {'name': 'rezak', 'version': '1'}})
        self.notify('notifications/initialized', {})

    def _read(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            with self.lock:
                if 'id' in message:
                    self.responses[message['id']] = message

    def notify(self, method, params):
        self.proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': method, 'params': params}) + '\n')
        self.proc.stdin.flush()

    def call(self, method, params, timeout=None):
        timeout = timeout or self.timeout
        with self.lock:
            self.counter += 1
            request_id = self.counter
        self.proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': request_id, 'method': method,
                                          'params': params}) + '\n')
        self.proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                if request_id in self.responses:
                    message = self.responses.pop(request_id)
                    if 'error' in message:
                        raise EngineError(str(message['error']))
                    return message.get('result') or {}
            time.sleep(0.05)
        raise EngineError(f'FilmCraft не ответил за {timeout} с')

    def tool(self, name, arguments, timeout=None):
        result = self.call('tools/call', {'name': name, 'arguments': arguments}, timeout)
        if result.get('isError'):
            raise EngineError(_flatten(result.get('content')))
        for block in result.get('content') or []:
            if block.get('type') == 'text':
                text = block['text']
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        return result

    def batch(self, steps):
        """Run commands in order and return the result payload of every step."""
        payload = self.tool('command_batch', {'steps': steps})
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                raise EngineError(payload)
        results = payload.get('results') or []
        for entry in results:
            if not entry.get('ok'):
                raise EngineError(f"{entry.get('id') or 'команда'}: {entry.get('error')}")
        return results

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            pass


def _flatten(content):
    if isinstance(content, list):
        return ' '.join(str(block.get('text', '')) for block in content if isinstance(block, dict))
    return str(content)


def _panel_filter(region, source_width, source_height, width, height):
    """Cut one region out of the source and fill the panel with it."""
    from .framing import crop_filter
    cover = f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}'
    whole = (region.x <= .001 and region.y <= .001 and region.w >= .999 and region.h >= .999)
    prefix = '' if whole else crop_filter(region, source_width, source_height) + ','
    return f'{prefix}{cover},setsar=1,fps={OUTPUT_FPS}'


def _cut_panel(source, target, region, source_width, source_height, width, height,
               start_ms, duration_ms, audio=False, cancel=None):
    """Extract one montage panel from the source with FFmpeg."""
    from .media import ffmpeg
    from .process import run
    args = [str(ffmpeg()), '-y', '-v', 'error', '-nostdin',
            '-ss', f'{start_ms / 1000:.3f}', '-t', f'{duration_ms / 1000:.3f}', '-i', str(source),
            '-vf', _panel_filter(region, source_width, source_height, width, height),
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p']
    args += ['-c:a', 'aac', '-ac', '2'] if audio else ['-an']
    args += [str(target)]
    run(args, timeout=max(120, duration_ms * 20), cancel=cancel)


def _caption_words(plan):
    """Caption items of the montage, one word at a time as in the reference."""
    from .subtitles import visible_captions
    words = []
    for caption in visible_captions(plan):
        text = caption.text.replace('\n', ' ').strip()
        if text:
            words.append({'text': text, 'start_ms': caption.start_ms, 'end_ms': caption.end_ms})
    return words


def render(plan, root, *, store=None, work=None, progress=None, cancel=None):
    """Render the reference montage with FilmCraft and return the exported file."""
    from .media import ffmpeg, probe, source_path
    from .plan import EditPlan
    from .process import run

    plan = plan if isinstance(plan, EditPlan) else EditPlan.model_validate(plan)
    engine = cli_path(store)
    if engine is None:
        raise EngineError('FilmCraft не найден: укажите путь к filmcraft-cli в настройках студии')
    style = get_style(plan.style)
    if style.key == 'default':
        raise EngineError('Движок FilmCraft собирает только стиль «Сплит лицо/игра»')
    if not caption_font_installed():
        install_caption_font()

    root = Path(root).resolve()
    source = source_path(root, plan.source_id)
    info = probe(source)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    source_width, source_height = int(video['width']), int(video['height'])
    width, height = OUTPUT_SIZE
    face_h, gap, bottom_h = style.panel_heights(height)

    exports = root / 'exports'
    exports.mkdir(parents=True, exist_ok=True)
    work = Path(work or (exports / 'filmcraft'))
    work.mkdir(parents=True, exist_ok=True)

    from .framing import webcam_region
    from .patterns import pattern_of
    from .plan import Region
    panels = []
    offset = 0
    for index, segment in enumerate(plan.segments):
        duration = segment.end_ms - segment.start_ms
        pattern = pattern_of(segment)
        if progress:
            progress(index / max(1, len(plan.segments)), 'Подготовка панелей монтажа')
        if pattern == 'split':
            # The screen carries the story: webcam panel on top, content below.
            camera = webcam_region(segment)
            game = segment.secondary_region or segment.region
            face_file = work / f'segment-{index}-face.mp4'
            game_file = work / f'segment-{index}-game.mp4'
            _cut_panel(source, face_file, camera, source_width, source_height, width, face_h,
                       segment.start_ms, duration)
            _cut_panel(source, game_file, game, source_width, source_height, width, bottom_h,
                       segment.start_ms, duration, audio=True, cancel=cancel)
            entries = [
                (game_file, 'V1', True, width, bottom_h, width // 2, face_h + gap + bottom_h // 2),
                (face_file, 'V2', False, width, face_h, width // 2, face_h // 2),
            ]
            replay = style.panel.replay
            if replay:
                px = round(width * replay[0])
                py = round(height * replay[1])
                pw = max(2, round(width * replay[2]) // 2 * 2)
                ph = max(2, round(height * replay[3]) // 2 * 2)
                replay_file = work / f'segment-{index}-replay.mp4'
                _cut_panel(source, replay_file, camera, source_width, source_height, pw, ph,
                           segment.start_ms, duration)
                entries.append((replay_file, 'V3', False, pw, ph, px + pw // 2, py + ph // 2))
        else:
            # Only the person (or only the screen) matters: one panel, full frame.
            region = segment.region or Region(x=0, y=0, w=1, h=1)
            full_file = work / f'segment-{index}-full.mp4'
            _cut_panel(source, full_file, region, source_width, source_height, width, height,
                       segment.start_ms, duration, audio=True, cancel=cancel)
            entries = [(full_file, 'V1', True, width, height, width // 2, height // 2)]
        panels.append({'offset': offset, 'duration': duration, 'pattern': pattern,
                       'entries': entries})
        offset += duration

    words = _caption_words(plan)
    session = Session(engine)
    try:
        media = [entry[0] for panel in panels for entry in panel['entries']]
        setup = session.batch([
            {'id': 'file.newProject', 'params': {'name': 'rezak'}},
            {'id': 'file.import', 'params': {'paths': [str(path).replace('\\', '/') for path in media]}},
            {'id': 'file.newSequence', 'params': {'name': 'rezak', 'width': width, 'height': height,
                                                 'fps': OUTPUT_FPS, 'sampleRate': 48000}},
            {'id': 'sequence.addTracks', 'params': {'video': 3, 'videoAfter': 'V1'}},
        ])
        items = setup[1]['result']['items']
        if len(items) != len(media):
            raise EngineError('FilmCraft импортировал не все панели')

        placements = []
        item_index = 0
        for panel in panels:
            start = panel['offset'] / 1000
            duration = panel['duration'] / 1000
            for path, track, audio, panel_width, panel_height, center_x, center_y in panel['entries']:
                placements.append((items[item_index], track, start, duration, audio,
                                   panel_width, panel_height, center_x, center_y))
                item_index += 1
        steps = [{'id': 'timeline.place', 'params': {
            'item': item, 'track': track, 'time': {'seconds': start},
            'duration': {'seconds': duration}, 'sourceIn': {'seconds': 0.0},
            'video': True, 'audio': audio}} for item, track, start, duration, audio,
            _, _, _, _ in placements]
        placed = session.batch(steps)
        for index, (_, _, _, _, _, panel_width, panel_height, center_x, center_y) in enumerate(placements):
            clip = placed[index]['result']['clips'][0]
            session.batch([
                {'id': 'effects.setParam', 'params': {'clip': clip, 'effect': 'motion',
                                                      'param': 'position', 'value': [center_x, center_y]}},
                {'id': 'effects.setParam', 'params': {'clip': clip, 'effect': 'motion',
                                                      'param': 'anchor',
                                                      'value': [panel_width // 2, panel_height // 2]}},
            ])

        size = style.caption.fc_size
        spans = []
        offset = 0
        for segment in plan.segments:
            spans.append((offset, offset + segment.end_ms - segment.start_ms, segment))
            offset += segment.end_ms - segment.start_ms
        for word in words:
            duration = max(0.3, (word['end_ms'] - word['start_ms']) / 1000)
            segment = next((item for left, right, item in spans if left <= word['start_ms'] < right), None)
            # The caption sits on the panel boundary in a split and in the
            # lower third of a single camera crop.
            center = style.caption_center(pattern_of(segment) if segment is not None else 'split')
            baseline = round(height * center + 0.3 * size)
            session.batch([
                {'id': 'graphics.newText', 'params': {
                    'text': word['text'], 'size': size, 'font': WIDE_FAMILY,
                    'fontStyle': 'ExtraBold', 'position': [width // 2, baseline],
                    'seconds': round(duration, 3),
                    'time': round(word['start_ms'] / 1000 * TICKS_PER_SECOND)}},
                {'id': 'graphics.set', 'params': {'props': {
                    'align': 'center', 'fill_color': '#ffffff', 'stroke': True,
                    'stroke_color': '#000000', 'stroke_width': style.caption.fc_stroke,
                    'stroke_type': 'outer'}}},
            ])

        destination = exports / f'{plan.source_id}-filmcraft-{int(time.time())}.mp4'
        if progress:
            progress(0.9, 'FilmCraft собирает ролик')
        session.batch([{'id': 'file.exportMedia', 'params': {
            'path': str(destination).replace('\\', '/'), 'format': 'h264', 'width': width,
            'height': height, 'fps': OUTPUT_FPS, 'wait': True}}])
    finally:
        session.close()
    if not destination.is_file():
        raise EngineError('FilmCraft не создал файл ролика')
    result = probe(destination)
    exported = next(s for s in result['streams'] if s['codec_type'] == 'video')
    if (exported['width'], exported['height']) != OUTPUT_SIZE:
        raise EngineError('FilmCraft вернул ролик неверного размера')
    destination.with_suffix('.plan.json').write_text(plan.model_dump_json(indent=2), encoding='utf-8')
    destination.with_suffix('.probe.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    if progress:
        progress(1.0, 'Ролик собран движком FilmCraft')
    return destination
