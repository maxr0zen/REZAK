"""Поиск стримов и клипов Twitch по игре для автоматических роликов."""
import re
import shutil
import subprocess
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from .plan import StrictModel

CLIP_MEDIA = 'https://clips-media-assets2.twitch.tv/{}-preview-480x272.mp4'
CLIP_ID = re.compile(r'[A-Za-z0-9_-]+')
WHITESPACE = re.compile(r'\s+')
CLIP_ERROR = 'Не удалось определить ссылку на ролик'
# The tag people actually search for is shorter than the name of the game.
GAME_TAGS = {
    'grand theft auto vi': 'gta_6',
    'grand theft auto v': 'gta_v',
    'grand theft auto': 'gta',
    'minecraft': 'minecraft',
    'counter-strike 2': 'cs2',
    'counter-strike': 'cs',
    'call of duty': 'cod',
    'league of legends': 'lol',
    'world of warcraft': 'wow',
    'grand theft auto online': 'gta_online',
}


class GameTarget(StrictModel):
    game_id: str
    game_name: str


class StreamerTarget(StrictModel):
    streamer_id: str
    login: str
    display_name: str
    viewers: int
    title: str
    game_name: str


class ClipTarget(StrictModel):
    clip_id: str
    streamer_id: str
    login: str
    title: str
    duration_ms: int
    view_count: int
    created_at: str
    url: str = ''


class CategoryCheck(StrictModel):
    """The result of comparing the requested game with the material's one."""
    verdict: Literal['match', 'mismatch', 'unknown']
    expected_id: str = ''
    expected_name: str = ''
    game_id: str = ''
    game_name: str = ''
    source: str = ''
    message: str = ''


def streamer_category(client, streamer_id):
    """The category the streamer is in right now, if the channel is live."""
    streams = client.get('streams', {'user_id': streamer_id, 'first': 1})
    if not streams:
        return None
    stream = streams[0]
    return {'game_id': str(stream.get('game_id') or ''), 'game_name': str(stream.get('game_name') or '')}


def _same_category(expected_id, expected_name, game_id, game_name):
    """Compare categories by Twitch id first and by name only as a fallback."""
    if expected_id and game_id:
        return str(expected_id) == str(game_id)
    if expected_name and game_name:
        left = WHITESPACE.sub(' ', str(expected_name)).strip().casefold()
        right = WHITESPACE.sub(' ', str(game_name)).strip().casefold()
        return left == right or left in right or right in left
    return False


def ytdlp_path():
    """The installed yt-dlp, if the machine has one."""
    for name in ('yt-dlp.exe', 'yt-dlp'):
        found = shutil.which(name)
        if found:
            return found
    return None


def download_clip(clip_url, target, *, timeout=300):
    """Fetch the media of a Twitch clip.

    Twitch signs its clip media now, so the plain preview link is usually
    refused with 403. yt-dlp asks for the signed link itself, so it is used
    when it is installed; the public preview stays as a fallback.
    """
    import httpx
    from .media import ffmpeg
    tool = ytdlp_path()
    if tool:
        args = [tool, '--no-playlist', '--no-warnings', '-f', 'best', '-o', str(target),
                '--ffmpeg-location', str(Path(ffmpeg()).parent), clip_url]
        try:
            result = subprocess.run(args, capture_output=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            result = None
        if result is not None and result.returncode == 0 and Path(target).is_file() \
                and Path(target).stat().st_size >= 1024:
            return Path(target)
    for url in clip_media_urls(clip_url):
        try:
            with httpx.stream('GET', url, follow_redirects=True, timeout=60) as response:
                if response.status_code != 200:
                    continue
                with open(target, 'wb') as stream:
                    for chunk in response.iter_bytes(65536):
                        stream.write(chunk)
        except httpx.HTTPError:
            continue
        if Path(target).is_file() and Path(target).stat().st_size >= 1024:
            return Path(target)
    raise ValueError('Twitch не отдал ролик')


def created_timestamp(value):
    """Unix time of an ISO timestamp from Twitch, or None."""
    text = (value or '').strip()
    if not text:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def check_category(expected_id, expected_name, *, current=None, observed=None):
    """Check that the material really belongs to the requested category.

    `current` is the category the streamer is in now, `observed` the category
    the studio recorded for the streamer at the time of the clip. A mismatch
    is a proven wrong category; no data at all is an unknown category, and the
    studio must not pass it off as a confirmed one.
    """
    expected_id = str(expected_id or '')
    expected_name = str(expected_name or '')
    for source, kind in ((current, 'сейчас в эфире'), (observed, 'записанная категория')):
        if not source or not source.get('game_id'):
            continue
        game_id = str(source.get('game_id') or '')
        game_name = str(source.get('game_name') or '')
        if _same_category(expected_id, expected_name, game_id, game_name):
            return CategoryCheck(verdict='match', expected_id=expected_id, expected_name=expected_name,
                                 game_id=game_id, game_name=game_name, source=kind,
                                 message='Категория совпадает: ' + (game_name or expected_name))
        return CategoryCheck(verdict='mismatch', expected_id=expected_id, expected_name=expected_name,
                             game_id=game_id, game_name=game_name, source=kind,
                             message=('Материал не из запрошенной категории: '
                                      + (game_name or 'неизвестная игра') + ' вместо '
                                      + (expected_name or 'запрошенной игры')))
    return CategoryCheck(verdict='unknown', expected_id=expected_id, expected_name=expected_name,
                         message='Категория не подтверждена: стример сейчас офлайн, а игра в его эфире неизвестна')


def find_game(client, name):
    query = (name or '').strip()
    if not query:
        raise ValueError('Укажите название игры')
    games = client.get('games', {'name': query})
    if not games:
        raise ValueError('Игра не найдена: ' + query)
    game = games[0]
    if not game.get('id'):
        raise ValueError('Игра не найдена: ' + query)
    return GameTarget(game_id=str(game['id']), game_name=str(game.get('name') or query))


def top_streamers(client, game_id, *, min_viewers=900, limit=25):
    # Twitch returns at most 100 streams per request. We deliberately do not paginate
    # further: the result covers the first page only.
    streams = client.get('streams', {'game_id': game_id, 'first': 100})
    rows = []
    for stream in streams:
        viewers = int(stream.get('viewer_count') or 0)
        if viewers < min_viewers:
            continue
        login = str(stream.get('user_login') or '')
        rows.append(StreamerTarget(
            streamer_id=str(stream.get('user_id') or ''),
            login=login,
            display_name=str(stream.get('user_name') or login),
            viewers=viewers,
            title=str(stream.get('title') or ''),
            game_name=str(stream.get('game_name') or '')))
    rows.sort(key=lambda row: row.viewers, reverse=True)
    return rows[:limit]


def streamer_clips(client, streamer_id, *, limit=20):
    # Twitch returns at most 100 clips per request; only that page is used.
    clips = client.get('clips', {'broadcaster_id': streamer_id, 'first': 100})
    rows = []
    for clip in clips:
        rows.append(ClipTarget(
            clip_id=str(clip.get('id') or ''),
            streamer_id=str(clip.get('broadcaster_id') or streamer_id),
            login=str(clip.get('broadcaster_login') or ''),
            title=str(clip.get('title') or ''),
            duration_ms=round(float(clip.get('duration') or 0) * 1000),
            view_count=int(clip.get('view_count') or 0),
            created_at=str(clip.get('created_at') or ''),
            url=str(clip.get('url') or '')))
    rows.sort(key=lambda row: row.view_count, reverse=True)
    return rows[:limit]


def _clip_location(value):
    parsed = urlparse(value)
    host = (parsed.netloc or '').lower()
    path = parsed.path
    if not host and not parsed.scheme:
        head, _, tail = value.partition('/')
        if head.lower().endswith('twitch.tv'):
            host = head.lower()
            path = '/' + tail
    return host, [part for part in path.split('/') if part]


def clip_media_url(clip_url):
    host, parts = _clip_location((clip_url or '').strip())
    if not (host == 'twitch.tv' or host.endswith('.twitch.tv')):
        raise ValueError(CLIP_ERROR)
    slug = ''
    if host == 'clips.twitch.tv':
        slug = parts[0] if parts else ''
    elif 'clip' in parts:
        # https://www.twitch.tv/<login>/clip/<Slug>
        index = len(parts) - 1 - parts[::-1].index('clip')
        slug = parts[index + 1] if index + 1 < len(parts) else ''
    if not slug or not CLIP_ID.fullmatch(slug):
        raise ValueError(CLIP_ERROR)
    return CLIP_MEDIA.format(slug)


def clip_media_urls(clip_url):
    """Download links of a clip, the sharper preview first."""
    primary = clip_media_url(clip_url)
    return [primary.replace('-preview-480x272.mp4', '-preview-960x540.mp4'), primary]


def hashtags(*parts):
    tags = []
    for part in parts:
        if part is None:
            continue
        text = WHITESPACE.sub(' ', str(part)).strip().lower()
        if not text:
            continue
        tag = GAME_TAGS.get(text, text.replace(' ', '_'))
        if tag not in tags:
            tags.append(tag)
    return tags


def build_title(hook, game, login, extra=None):
    text = (hook or '').strip() or (game or '').strip()
    text = text[:120]
    extras = []
    if extra:
        extras = [extra] if isinstance(extra, str) else list(extra)
    tags = hashtags(game, login, *extras)
    # A tag that the headline already carries is not repeated in the title.
    tags = [tag for tag in tags if '#' + tag not in text.casefold()]
    parts = [text] if text else []
    parts += ['#' + tag for tag in tags]
    return ' '.join(parts)


def word_captions(transcript, start_ms=0, end_ms=None, *, minimum_probability=0.0,
                  minimum_duration=400, maximum_length=12):
    """Speech captions of the window, one phrase at a time as in the reference.

    The words keep their own timecodes, so the caption changes with the
    speech instead of covering the whole clip with a fixed line. Words that
    overlap in the sound are shown one after another: two captions on top of
    each other cannot be read at all. A caption never runs past the start of
    the next one, so the captions stay on the words that are spoken.
    """
    stop = end_ms if end_ms is not None else 10 ** 9
    words = []
    for segment in transcript.get('segments', []):
        for word in segment.get('words', []):
            begin, end = word['start_ms'], word['end_ms']
            if end <= start_ms or begin >= stop:
                continue
            text = (word.get('text') or '').strip()
            if not text:
                continue
            if minimum_probability > 0 and word.get('probability', 1.0) < minimum_probability:
                # The recognition of game audio is noisy: a word the model is
                # not sure about is better left out than shown wrong.
                continue
            words.append({'start_ms': max(start_ms, begin), 'end_ms': min(stop, end), 'text': text})
    words.sort(key=lambda word: word['start_ms'])
    groups = []
    for word in words:
        if groups:
            previous = groups[-1]
            if word['start_ms'] < previous['end_ms'] - 40:
                combined = previous['text'] + ' ' + word['text']
                if len(combined) <= maximum_length:
                    # Two short words fit the line of the reference.
                    previous['text'] = combined
                    previous['end_ms'] = max(previous['end_ms'], word['end_ms'])
                    continue
                # A long word waits until the previous caption is done.
                word = dict(word, start_ms=previous['end_ms'] + 40)
        groups.append({'start_ms': word['start_ms'], 'end_ms': word['end_ms'], 'text': word['text']})
    lines = []
    for group in groups:
        if lines:
            previous = lines[-1]
            combined = previous['text'] + ' ' + group['text']
            brief = previous['end_ms'] - previous['start_ms'] < 150
            close = group['start_ms'] - previous['end_ms'] <= 300
            if brief and close and len(combined) <= maximum_length:
                # A caption of a single short word is unreadable: the next
                # word joins it, and the timecodes of the words stay the same.
                previous['text'] = combined
                previous['end_ms'] = max(previous['end_ms'], group['end_ms'])
                continue
        lines.append(group)
    result = []
    for index, group in enumerate(lines):
        start = group['start_ms']
        if result:
            start = max(start, result[-1]['end_ms'])
        if start >= stop:
            break
        following = lines[index + 1]['start_ms'] if index + 1 < len(lines) else stop
        limit = max(start, min(stop, following))
        end = min(max(group['end_ms'], start), limit)
        if end - start < minimum_duration:
            # The caption is shown long enough to be read, but not past the
            # next word: a stretched caption would push the words that follow.
            end = min(start + minimum_duration, limit)
        result.append({'start_ms': start, 'end_ms': max(end, min(start + 1, limit)),
                       'text': group['text'], 'kind': 'word', 'reason': ''})
    return result


def clip_plan(source_id, duration_ms, width, height, *, title='', hook_title='', pattern=None,
              captions=()):
    """Plan for a downloaded Twitch clip.

    The pattern comes from the footage: a split when the screen carries the
    story, a single camera crop when the camera fills the frame. Splitting a
    full-screen webcam would put a cropped camera above the same camera.
    """
    from .patterns import Pattern, SPLIT, apply_pattern
    from .plan import Caption, EditPlan, Region, Segment
    if pattern is None:
        # Fallback for callers without a detection: a centred crop above the
        # clip as a whole, which is the split geometry of the reference.
        aspect = 1080 / 810
        if width and height and width / height > aspect:
            w = height * aspect / width
            region = Region(x=round((1 - w) / 2, 4), y=0.0, w=round(w, 4), h=1.0)
        else:
            h = (width / aspect / height) if width and height else 1.0
            region = Region(x=0.0, y=round((1 - h) / 2, 4), w=1.0, h=round(h, 4))
        pattern = Pattern(SPLIT, region, Region(x=0.0, y=0.0, w=1.0, h=1.0),
                          'Паттерн не определён')
    segment = Segment(start_ms=0, end_ms=max(1, int(duration_ms)), framing='fit',
                      framing_note='Тикток по игре: ' + pattern.label)
    segment = apply_pattern(segment, pattern)
    return EditPlan(schema_version=1, source_id=source_id, profile='vertical',
                    title=title[:240], hook_title=hook_title[:84], style='t2x2',
                    segments=[segment],
                    captions=[Caption(**caption) for caption in captions])
