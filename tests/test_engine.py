"""Монтажный движок: выбор движка, применение стиля, режим «тиктоки по играм»."""
import pytest
from fastapi.testclient import TestClient

from rezak.engine import apply_style, engine_name, style_from_environment, style_name
from rezak.plan import EditPlan, Region
from rezak.web import create_app


@pytest.fixture
def studio(tmp_path):
    app = create_app(tmp_path, start_background=False, testing=True)
    with TestClient(app, headers={'X-Rezak-Client': '1'}) as client:
        yield client, app.state.store, app


def plan(**kwargs):
    segment = {
        'start_ms': 0, 'end_ms': 8000, 'framing': 'crop',
        'region': {'x': 0.1, 'y': 0.1, 'w': 0.3, 'h': 0.3},
        'secondary_region': {'x': 0.0, 'y': 0.0, 'w': 1.0, 'h': 1.0}}
    segment.update(kwargs.pop('segment', {}))
    data = {'schema_version': 1, 'source_id': 'demo', 'profile': 'vertical',
            'segments': [segment]}
    data.update(kwargs)
    return EditPlan.model_validate(data)


def test_engine_and_style_follow_the_studio_settings(studio):
    _, store, _ = studio
    assert engine_name(store) == 'ffmpeg'
    assert style_name(store) == 'default'
    store.set_setting('render_engine', 'filmcraft')
    store.set_setting('montage_style', 't2x2')
    assert engine_name(store) == 'filmcraft'
    assert style_name(store) == 't2x2'
    store.set_setting('render_engine', 'unknown')
    assert engine_name(store) == 'ffmpeg'


def test_style_from_environment_reads_the_pipeline_request(monkeypatch):
    monkeypatch.delenv('REZAK_MONTAGE_STYLE', raising=False)
    assert style_from_environment() == 'default'
    monkeypatch.setenv('REZAK_MONTAGE_STYLE', 't2x2')
    assert style_from_environment() == 't2x2'
    monkeypatch.setenv('REZAK_MONTAGE_STYLE', 'nonsense')
    assert style_from_environment() == 'default'


def test_apply_style_marks_the_style_without_touching_the_geometry():
    styled = apply_style(plan(), 't2x2')
    assert styled.style == 't2x2'
    segment = styled.segments[0]
    # The picture follows the footage, not the style name: a split or a single
    # camera crop is decided by the pattern detector.
    assert segment.framing == 'crop'
    assert segment.region == Region(x=0.1, y=0.1, w=0.3, h=0.3)
    assert segment.secondary_region == Region(x=0.0, y=0.0, w=1.0, h=1.0)


def test_style_plan_picks_the_pattern_from_the_footage(monkeypatch):
    from rezak import patterns
    from rezak.engine import style_plan
    monkeypatch.setattr(patterns, 'detect', lambda *args, **kwargs: patterns.Pattern(
        patterns.FACE, Region(x=0.2, y=0.0, w=0.6, h=1.0), None, 'тест'))
    automatic = plan(segment={'framing': 'fit', 'region': None, 'secondary_region': None,
                               'framing_note': 'Авто: геометрия проверена на трёх кадрах.'})
    styled = style_plan(automatic, 't2x2', 'source.mp4')
    assert styled.style == 't2x2'
    assert styled.segments[0].framing == 'crop'
    assert styled.segments[0].region == Region(x=0.2, y=0.0, w=0.6, h=1.0)
    assert styled.segments[0].secondary_region is None


def test_apply_style_keeps_the_default_style_untouched():
    plain = plan()
    assert apply_style(plain, 'default').model_dump() == plain.model_dump()


def test_montage_settings_are_saved_and_reported(studio):
    client, store, _ = studio
    response = client.post('/api/montage-settings', json={
        'render_engine': 'filmcraft', 'filmcraft_cli': 'C:/tools/filmcraft-cli.exe',
        'montage_style': 't2x2'})
    assert response.status_code == 200
    assert response.json()['render_engine'] == 'filmcraft'
    assert response.json()['montage_style'] == 't2x2'
    settings = client.get('/api/settings').json()
    assert settings['render_engine'] == 'filmcraft'
    assert settings['montage_style'] == 't2x2'
    assert settings['filmcraft_cli'] == 'C:/tools/filmcraft-cli.exe'
    assert 'filmcraft_available' in settings and 'caption_font_installed' in settings
    assert store.setting('render_engine') == 'filmcraft'


def test_games_endpoints_need_twitch_credentials(studio):
    client, _, _ = studio
    assert client.get('/api/games', params={'query': 'GTA 6'}).status_code == 409
    assert client.get('/api/games/clips', params={'streamer_id': '42'}).status_code == 409


def test_games_clip_endpoint_rejects_foreign_links(studio):
    client, _, _ = studio
    response = client.post('/api/games/tiktok', json={
        'clip_url': 'https://youtube.com/watch?v=abc', 'game': 'GTA 6', 'login': '5opka'})
    assert response.status_code == 400
    assert 'Не удалось определить ссылку' in response.json()['detail']


def test_games_clip_endpoint_refuses_material_from_another_category(studio):
    client, _, app = studio

    class FakeTwitch:
        def configured(self):
            return True

        def get(self, resource, params):
            if resource == 'streams':
                return [{'id': '1', 'user_id': '42', 'user_login': '5opka', 'user_name': '5opka',
                         'game_id': '1200', 'game_name': 'Fortnite', 'viewer_count': 1200}]
            return []

    app.state.monitor.client = FakeTwitch()
    response = client.post('/api/games/tiktok', json={
        'clip_url': 'https://clips.twitch.tv/AwkwardHelplessSalamanderSwiftRage',
        'game': 'GTA 6', 'game_id': '509658', 'streamer_id': '42'})
    assert response.status_code == 409
    assert 'Fortnite' in response.json()['detail']
