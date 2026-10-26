import json
from pathlib import Path

import pytest
from rezak.backgrounds import select_background, stack_layout
from rezak.plan import EditPlan
from rezak.subtitles import write_ass


def plan(**extra):
    return EditPlan(schema_version=1,source_id='synthetic',profile='vertical',
                    title='Тест фона',hook_title='Заголовок ниже',
                    segments=[{'start_ms':0,'end_ms':1000}],
                    captions=[{'start_ms':0,'end_ms':900,'text':'Проверка субтитров'}],**extra)


def library(root, name='parkour.mp4'):
    directory=root/'backgrounds';directory.mkdir()
    (directory/'library.json').write_text(json.dumps({'enabled':True,'assets':[
        {'file':name,'license':'CC BY 3.0','source_url':'https://example.com/parkour'}]}))
    return directory


def test_no_asset_means_legacy_layout_and_horizontal_unchanged(tmp_path):
    assert select_background(plan(),tmp_path) is None
    assert select_background(plan().model_copy(update={'profile':'horizontal'}),tmp_path) is None


def test_background_selection_is_local_and_reproducible(tmp_path):
    d=library(tmp_path);(d/'parkour.mp4').write_bytes(b'media fixture')
    selected=select_background(plan(),tmp_path)
    assert selected==select_background(plan(),tmp_path)
    assert selected[0]==(d/'parkour.mp4').resolve()
    (d/'parkour.mp4').unlink()
    with pytest.raises(ValueError):select_background(plan(),tmp_path)


def test_background_cannot_escape_library(tmp_path):
    library(tmp_path,'../secret.mp4')
    with pytest.raises(ValueError):select_background(plan(),tmp_path)


def test_stream_and_captions_above_filler_without_cropping(tmp_path):
    p=plan()
    header,content,band,start,bottom=stack_layout(p.segments[0],720,1280,1920,1080)
    assert header==0 and content==404
    assert header+content+band==start and start+bottom==1280
    path=tmp_path/'captions.ass';write_ass(p,path,source_size=(1920,1080),background=True)
    text=path.read_text(encoding='utf-8')
    assert r'\pos(540,96)' in text
    assert f'\\pos(540,{round((header+content+band/2)*1.5)})' in text


def test_captions_stay_fixed_when_headline_disappears(tmp_path):
    p=plan().model_copy(update={'segments':[plan().segments[0].model_copy(update={'end_ms':7000})]})
    from rezak.plan import Caption
    p.captions=[Caption(start_ms=4800,end_ms=5500,text='Переход'),Caption(start_ms=6000,end_ms=6800,text='После')]
    path=tmp_path/'timed.ass';write_ass(p,path,source_size=(1920,1080),background=True)
    text=path.read_text(encoding='utf-8')
    assert r'\move(' not in text
    assert text.count(r'\pos(540,672)')==2


@pytest.mark.skipif(__import__('os').environ.get('REZAK_INTEGRATION')!='1',reason='FFmpeg integration')
def test_real_background_render_loops_and_keeps_source_audio(tmp_path):
    from rezak.web import configure_tools
    from rezak.render import render
    from rezak.media import probe
    import shutil
    configure_tools(Path.cwd())
    (tmp_path/'sources').mkdir()
    shutil.copyfile('data/sources/synthetic.mp4',tmp_path/'sources/synthetic.mp4')
    d=library(tmp_path);shutil.copyfile('data/sources/synthetic.mp4',d/'parkour.mp4')
    p=plan().model_copy(update={'segments':[plan().segments[0].model_copy(update={'start_ms':0,'end_ms':4000}),plan().segments[0].model_copy(update={'start_ms':4000,'end_ms':6000})]})
    result=render(p,tmp_path);info=probe(result)
    assert abs(float(info['format']['duration'])-6)<.15
    video=next(s for s in info['streams'] if s['codec_type']=='video')
    assert (video['width'],video['height'])==(720,1280)
    audio=next(s for s in info['streams'] if s['codec_type']=='audio')
    assert audio['channels']==2
    assert json.loads(result.with_suffix('.edit.json').read_text(encoding='utf-8'))['background_credit']['file']=='parkour.mp4'
    import cv2
    video=cv2.VideoCapture(str(result))
    try:
        video.set(cv2.CAP_PROP_POS_MSEC,500);ok,before=video.read();assert ok
        video.set(cv2.CAP_PROP_POS_MSEC,5500);ok,after=video.read();assert ok
        assert before[:30,:30].mean()>20
        assert after[:30,:30].mean()>20
    finally:video.release()
