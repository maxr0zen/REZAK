import httpx
import pytest
from pathlib import Path

from rezak.games import (build_title, check_category, clip_media_url, clip_plan, find_game, hashtags,
                         streamer_clips, top_streamers)


class FakeClient:
    """Заглушка Helix: отдаёт заранее заданные данные и запоминает запросы."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def get(self, resource, params):
        self.calls.append((resource, params))
        return self.responses.get(resource, [])


def test_find_game_returns_first_match_and_reports_missing_game():
    client = FakeClient({'games': [{'id': '509658', 'name': 'Grand Theft Auto VI'}]})
    game = find_game(client, 'GTA 6')
    assert game.game_id == '509658'
    assert game.game_name == 'Grand Theft Auto VI'
    assert client.calls == [('games', {'name': 'GTA 6'})]
    with pytest.raises(ValueError, match='Игра не найдена'):
        find_game(FakeClient({'games': []}), 'GTA 6')
    with pytest.raises(ValueError, match='Укажите название игры'):
        find_game(client, '   ')


def test_top_streamers_filters_sorts_and_limits():
    streams = [
        {'user_id': '1', 'user_login': 'low', 'user_name': 'Low', 'viewer_count': 120,
         'title': 'мало', 'game_name': 'GTA 6'},
        {'user_id': '2', 'user_login': 'top', 'user_name': 'Top', 'viewer_count': 5000,
         'title': 'много', 'game_name': 'GTA 6'},
        {'user_id': '3', 'user_login': 'edge', 'user_name': 'Edge', 'viewer_count': 900,
         'title': 'ровно порог', 'game_name': 'GTA 6'},
    ]
    client = FakeClient({'streams': streams})
    rows = top_streamers(client, '509658')
    assert [row.login for row in rows] == ['top', 'edge']
    assert rows[0].streamer_id == '2'
    assert rows[0].display_name == 'Top'
    assert rows[0].viewers == 5000
    assert rows[0].title == 'много'
    assert rows[0].game_name == 'GTA 6'
    assert client.calls == [('streams', {'game_id': '509658', 'first': 100})]
    assert [row.login for row in top_streamers(client, '509658', min_viewers=500, limit=1)] == ['top']
    assert top_streamers(client, '509658', min_viewers=10000) == []


def test_streamer_clips_sort_by_views_and_convert_duration():
    clips = [
        {'id': 'ClipOne', 'broadcaster_id': '42', 'broadcaster_login': '5opka', 'title': 'первый',
         'duration': 30.5, 'view_count': 10, 'created_at': '2026-01-01T00:00:00Z'},
        {'id': 'ClipTwo', 'broadcaster_id': '42', 'broadcaster_login': '5opka', 'title': 'второй',
         'duration': 12.0, 'view_count': 900, 'created_at': '2026-01-02T00:00:00Z'},
    ]
    client = FakeClient({'clips': clips})
    rows = streamer_clips(client, '42')
    assert [row.clip_id for row in rows] == ['ClipTwo', 'ClipOne']
    assert rows[0].duration_ms == 12000
    assert rows[1].duration_ms == 30500
    assert rows[0].view_count == 900
    assert rows[0].created_at == '2026-01-02T00:00:00Z'
    assert rows[0].streamer_id == '42'
    assert rows[0].login == '5opka'
    assert client.calls == [('clips', {'broadcaster_id': '42', 'first': 100})]
    assert len(streamer_clips(client, '42', limit=1)) == 1


def test_clip_media_url_supports_both_link_shapes():
    expected = 'https://clips-media-assets2.twitch.tv/AwkwardHelplessSalamanderSwiftRage-preview-480x272.mp4'
    assert clip_media_url('https://clips.twitch.tv/AwkwardHelplessSalamanderSwiftRage') == expected
    assert clip_media_url('https://www.twitch.tv/5opka/clip/AwkwardHelplessSalamanderSwiftRage') == expected
    assert clip_media_url('https://clips.twitch.tv/SomeSlug') == \
        'https://clips-media-assets2.twitch.tv/SomeSlug-preview-480x272.mp4'
    for broken in ('https://youtube.com/watch?v=abc', 'https://www.twitch.tv/5opka', '', 'мусор'):
        with pytest.raises(ValueError, match='Не удалось определить ссылку на ролик'):
            clip_media_url(broken)


def test_clip_media_urls_prefer_the_sharper_preview():
    from rezak.games import clip_media_urls
    urls = clip_media_urls('https://clips.twitch.tv/AwkwardHelplessSalamanderSwiftRage')
    assert urls[0].endswith('-preview-960x540.mp4')
    assert urls[1].endswith('-preview-480x272.mp4')


def test_hashtags_keep_cyrillic_lowercase_and_order():
    assert hashtags('GTA 6', '5opka', '2х2') == ['gta_6', '5opka', '2х2']
    assert hashtags('GTA 6', 'gta_6', '  ') == ['gta_6']
    assert hashtags('Привет Мир') == ['привет_мир']
    assert hashtags() == []


def test_hashtags_use_the_short_tag_of_a_known_game():
    assert hashtags('Grand Theft Auto VI') == ['gta_6']
    assert hashtags('Grand Theft Auto V') == ['gta_v']
    assert hashtags('Counter-Strike 2') == ['cs2']
    assert build_title('', 'Grand Theft Auto VI', 'xqc') == 'Grand Theft Auto VI #gta_6 #xqc'


def test_build_title_follows_the_reference_format():
    assert build_title('2х2 помог протестующим', 'GTA 6', '5opka') == '2х2 помог протестующим #gta_6 #5opka'
    assert build_title('', 'GTA 6', '5opka') == 'GTA 6 #gta_6 #5opka'
    assert build_title('   ', 'GTA 6', '5opka', ['2х2']) == 'GTA 6 #gta_6 #5opka #2х2'
    assert build_title('x' * 200, 'GTA 6', '5opka').startswith('x' * 120)
    assert len(build_title('x' * 200, 'GTA 6', '5opka')) == 120 + len(' #gta_6 #5opka')


def test_streamer_clips_keep_the_clip_link():
    client = FakeClient({'clips': [{
        'id': 'ClipOne', 'broadcaster_id': '42', 'broadcaster_login': '5opka', 'title': 'первый',
        'duration': 30.5, 'view_count': 10, 'created_at': '2026-01-01T00:00:00Z',
        'url': 'https://clips.twitch.tv/AwkwardHelplessSalamanderSwiftRage'}]})
    rows = streamer_clips(client, '42')
    assert rows[0].url == 'https://clips.twitch.tv/AwkwardHelplessSalamanderSwiftRage'
    assert clip_media_url(rows[0].url).endswith('-preview-480x272.mp4')


def test_clip_plan_uses_the_reference_split_geometry():
    plan = clip_plan('gameclip-1', 30000, 1920, 1080, title='GTA 6 #gta_6')
    assert plan.style == 't2x2'
    assert plan.profile == 'vertical'
    segment = plan.segments[0]
    assert segment.framing == 'split'
    assert segment.start_ms == 0 and segment.end_ms == 30000
    # the upper panel keeps the aspect of the reference face panel
    assert (segment.region.w * 1920) / (segment.region.h * 1080) == pytest.approx(1080 / 810, rel=1e-3)
    assert segment.region.x == pytest.approx((1 - segment.region.w) / 2, abs=1e-3)
    assert segment.secondary_region.w == 1 and segment.secondary_region.h == 1
    portrait = clip_plan('gameclip-2', 30000, 1080, 1920)
    assert portrait.segments[0].region.w == 1
    assert (portrait.segments[0].region.w * 1080) / (portrait.segments[0].region.h * 1920) == \
        pytest.approx(1080 / 810, rel=1e-3)


def test_helix_errors_are_propagated():
    class Broken:
        def get(self, resource, params):
            raise httpx.HTTPStatusError('403 Forbidden', request=httpx.Request('GET', 'https://api.twitch.tv/helix/streams'),
                                         response=httpx.Response(403))

    with pytest.raises(httpx.HTTPStatusError):
        top_streamers(Broken(), '509658')
    with pytest.raises(httpx.HTTPStatusError):
        find_game(Broken(), 'GTA 6')
    with pytest.raises(httpx.HTTPStatusError):
        streamer_clips(Broken(), '42')


def test_category_check_compares_the_material_with_the_requested_game():
    match = check_category('509658', 'Grand Theft Auto VI',
                           current={'game_id': '509658', 'game_name': 'Grand Theft Auto VI'})
    assert match.verdict == 'match'
    assert match.game_name == 'Grand Theft Auto VI'
    mismatch = check_category('509658', 'Grand Theft Auto VI',
                              current={'game_id': '1200', 'game_name': 'Fortnite'})
    assert mismatch.verdict == 'mismatch'
    assert 'Fortnite' in mismatch.message
    unknown = check_category('509658', 'Grand Theft Auto VI')
    assert unknown.verdict == 'unknown'
    assert 'не подтверждена' in unknown.message


def test_category_check_falls_back_to_the_recorded_history():
    observed = {'game_id': '1200', 'game_name': 'Fortnite'}
    assert check_category('509658', 'GTA 6', observed=observed).verdict == 'mismatch'
    assert check_category('1200', 'Fortnite', observed=observed).verdict == 'match'


def test_store_keeps_the_history_of_stream_categories(tmp_path):
    from rezak.store import Store
    store = Store(tmp_path)
    store.record_category('42', '509658', 'Grand Theft Auto VI', 1000)
    store.record_category('42', '509658', 'Grand Theft Auto VI', 1100)
    store.record_category('42', '1200', 'Fortnite', 1200)
    history = store.categories_for('42')
    assert len(history) == 2
    assert store.category_at('42', 1050)['game_id'] == '509658'
    assert store.category_at('42', 1250)['game_id'] == '1200'
    assert store.category_at('99', 1050) is None


def test_clip_download_prefers_yt_dlp_for_signed_links(tmp_path, monkeypatch):
    import subprocess

    from rezak import games
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        Path(args[args.index('-o') + 1]).write_bytes(b'0' * 4096)
        return subprocess.CompletedProcess(args, 0, b'', b'')

    monkeypatch.setattr(games, 'ytdlp_path', lambda: 'yt-dlp')
    monkeypatch.setattr(games.subprocess, 'run', fake_run)
    target = tmp_path / 'clip.mp4'
    games.download_clip('https://clips.twitch.tv/AwkwardHelplessSalamanderSwiftRage', target)
    assert target.stat().st_size == 4096
    assert calls and calls[0][0] == 'yt-dlp'


def test_clip_download_falls_back_to_the_public_preview(tmp_path, monkeypatch):
    from rezak import games

    class FakeResponse:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_bytes(self, size):
            return [b'0' * 2048]

    monkeypatch.setattr(games, 'ytdlp_path', lambda: None)
    monkeypatch.setattr(httpx, 'stream', lambda *args, **kwargs: FakeResponse())
    target = tmp_path / 'clip.mp4'
    games.download_clip('https://clips.twitch.tv/AwkwardHelplessSalamanderSwiftRage', target)
    assert target.is_file() and target.stat().st_size == 2048


def test_word_captions_keep_the_timecodes_of_the_speech():
    from rezak.games import word_captions
    transcript = {'segments': [{'start_ms': 1000, 'end_ms': 4000, 'text': ' Привет мир', 'words': [
        {'start_ms': 1000, 'end_ms': 1500, 'text': ' Привет', 'probability': 0.9},
        {'start_ms': 1500, 'end_ms': 2000, 'text': ' мир', 'probability': 0.8},
        {'start_ms': 5000, 'end_ms': 5400, 'text': ' да', 'probability': 0.9},
    ]}]}
    captions = word_captions(transcript, 0, 4000)
    assert [caption['text'] for caption in captions] == ['Привет', 'мир']
    assert captions[0]['start_ms'] == 1000 and captions[0]['end_ms'] == 1500
    assert captions[0]['kind'] == 'word'


def test_word_captions_do_not_push_the_words_that_follow():
    """A short word must not shift the next caption away from the speech."""
    from rezak.games import word_captions
    transcript = {'segments': [{'start_ms': 0, 'end_ms': 3000, 'text': '', 'words': [
        {'start_ms': 0, 'end_ms': 40, 'text': ' я', 'probability': 0.9},
        {'start_ms': 100, 'end_ms': 600, 'text': ' смотрю', 'probability': 0.9},
        {'start_ms': 1200, 'end_ms': 1600, 'text': ' кнопку', 'probability': 0.9},
    ]}]}
    captions = word_captions(transcript, 0, 3000)
    assert [caption['text'] for caption in captions] == ['я смотрю', 'кнопку']
    assert captions[0]['start_ms'] == 0
    assert captions[1]['start_ms'] == 1200
    assert captions[1]['end_ms'] == 1600
    for index, caption in enumerate(captions[:-1]):
        assert caption['end_ms'] <= captions[index + 1]['start_ms']


def test_word_captions_keep_a_long_caption_from_covering_the_next_words():
    from rezak.games import word_captions
    transcript = {'segments': [{'start_ms': 0, 'end_ms': 3000, 'text': '', 'words': [
        {'start_ms': 0, 'end_ms': 120, 'text': ' что', 'probability': 0.9},
        {'start_ms': 200, 'end_ms': 900, 'text': ' произошло', 'probability': 0.9},
        {'start_ms': 1000, 'end_ms': 1500, 'text': ' дальше', 'probability': 0.9},
    ]}]}
    captions = word_captions(transcript, 0, 3000)
    assert [caption['text'] for caption in captions] == ['что', 'произошло', 'дальше']
    assert captions[0]['end_ms'] <= captions[1]['start_ms']
    assert captions[1]['start_ms'] == 200
    assert captions[2]['start_ms'] == 1000


def test_word_captions_drop_the_words_the_model_is_not_sure_about():
    from rezak.games import word_captions
    transcript = {'segments': [{'start_ms': 0, 'end_ms': 2000, 'text': '', 'words': [
        {'start_ms': 0, 'end_ms': 500, 'text': ' Конечно', 'probability': 0.9},
        {'start_ms': 500, 'end_ms': 900, 'text': ' наверное', 'probability': 0.2},
    ]}]}
    captions = word_captions(transcript, 0, 2000, minimum_probability=0.25)
    assert [caption['text'] for caption in captions] == ['Конечно']


def test_clip_plan_carries_the_captions_into_the_plan():
    from rezak.games import clip_plan
    plan = clip_plan('gameclip-1', 12000, 1920, 1080, title='GTA 6', captions=[
        {'start_ms': 100, 'end_ms': 900, 'text': 'Привет', 'kind': 'word', 'reason': ''}])
    assert len(plan.captions) == 1
    assert plan.captions[0].text == 'Привет'
    assert plan.captions[0].kind == 'word'


def test_asr_runner_finds_the_newest_transcript(tmp_path):
    import json
    import os

    from rezak.asr_runner import transcript_path
    directory = tmp_path / 'data' / 'transcripts'
    directory.mkdir(parents=True)
    assert transcript_path(tmp_path, 'gameclip-1') is None
    first = directory / 'gameclip-1-aaa.json'
    first.write_text(json.dumps({'segments': []}), encoding='utf-8')
    os.utime(first, (1, 1))
    second = directory / 'gameclip-1-bbb.json'
    second.write_text(json.dumps({'segments': [{'start_ms': 0}]}), encoding='utf-8')
    assert transcript_path(tmp_path, 'gameclip-1') == second
    # A file that is not a transcript is never taken for one.
    stray = directory / 'gameclip-1-ccc.json'
    stray.write_text('{}', encoding='utf-8')
    assert transcript_path(tmp_path, 'gameclip-1') == second
