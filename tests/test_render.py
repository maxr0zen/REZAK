import os
from pathlib import Path
import pytest
from rezak.plan import EditPlan
from rezak.render import render
from rezak.media import probe

@pytest.mark.parametrize('profile,size', [('vertical',(720,1280)),('horizontal',(1920,1080))])
def test_real_render(profile,size):
    if not os.environ.get('REZAK_INTEGRATION'):
        pytest.skip('Set REZAK_INTEGRATION=1 and FFMPEG/FFPROBE; run scripts.smoke first')
    plan=EditPlan(schema_version=1,source_id='synthetic',profile=profile,segments=[{'start_ms':1000,'end_ms':2000}])
    output=render(plan,Path('data'))
    result=probe(output)
    video=next(s for s in result['streams'] if s['codec_type']=='video')
    assert (video['width'],video['height'])==size
    assert abs(float(result['format']['duration'])-1)<.15
    assert output.with_suffix('.plan.json').exists()

def test_real_1080_montage_preserves_multiple_cuts_and_title():
    if os.environ.get('REZAK_INTEGRATION')!='1':pytest.skip('FFmpeg integration')
    from rezak.clips import ClipLibrary
    plan=EditPlan(schema_version=1,source_id='synthetic',profile='horizontal',title='Проверка связанного монтажа',
                  segments=[{'start_ms':0,'end_ms':1000},{'start_ms':2000,'end_ms':3000},{'start_ms':4000,'end_ms':5000}],
                  captions=[{'start_ms':4000,'end_ms':4900,'text':'Финал'}])
    output=render(plan,Path('data'));info=probe(output)
    assert abs(float(info['format']['duration'])-3)<.15
    assert ClipLibrary(Path('data')).metadata(output)['title']==plan.title

def test_real_late_short_uses_seek_and_stays_720p():
    if os.environ.get('REZAK_INTEGRATION')!='1':pytest.skip('FFmpeg integration')
    plan=EditPlan(schema_version=1,source_id='synthetic',profile='vertical',segments=[{'start_ms':4000,'end_ms':5000}])
    info=probe(render(plan,Path('data')))
    video=next(s for s in info['streams'] if s['codec_type']=='video')
    assert (video['width'],video['height'])==(720,1280)
    assert abs(float(info['format']['duration'])-1)<.15
