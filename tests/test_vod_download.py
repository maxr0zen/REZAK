import importlib.util
from pathlib import Path
import pytest

@pytest.fixture
def downloader():
    path=Path(__file__).parents[1]/'scripts/download-vod.py'
    spec=importlib.util.spec_from_file_location('vod_download_test',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

@pytest.mark.parametrize('url',['https://example.com/videos/123','https://twitch.tv/videos/../../secret','http://twitch.tv/videos/123','https://twitch.tv.evil.test/videos/123','https://twitch.tv/videos/not-an-id'])
def test_rejects_non_vod_urls(downloader,url):
    with pytest.raises(ValueError):downloader.download(url)

@pytest.mark.parametrize('name',['recording.ts','recording.part.ts'])
def test_existing_download_is_never_overwritten(downloader,tmp_path,monkeypatch,name):
    monkeypatch.setattr(downloader,'__file__',str(tmp_path/'scripts/download-vod.py'))
    folder=tmp_path/'data/recordings/vod_123';folder.mkdir(parents=True);path=folder/name;path.write_bytes(b'keep original')
    def no_process(*args,**kwargs):raise AssertionError('Must refuse before starting a network process')
    monkeypatch.setattr(downloader.subprocess,'run',no_process)
    with pytest.raises(ValueError):downloader.download('https://www.twitch.tv/videos/123')
    assert path.read_bytes()==b'keep original'
