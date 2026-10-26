import pytest
from pydantic import ValidationError
from rezak.plan import EditPlan,Region
from rezak.subtitles import write_ass

def plan(**extra):
    return EditPlan(schema_version=1,source_id='test',profile='vertical',segments=[{'start_ms':0,'end_ms':10000}],**extra)

def test_headline_is_separate_five_second_layer_without_speech(tmp_path):
    p=plan(hook_title='Пятёрка озвучивает лучше Голливуда')
    path=tmp_path/'headline.ass'
    assert write_ass(p,path)
    text=path.read_text(encoding='utf-8')
    assert 'Dialogue: 2,0:00:00.00,0:00:05.00' in text
    assert r'\an8\pos(540,96)' in text
    assert 'ПЯТЁРКА ОЗВУЧИВАЕТ' in text

@pytest.mark.parametrize('text',['{\\pos(0,0)}','bad\nheading','bad\\heading'])
def test_generated_headline_cannot_inject_ass(text):
    with pytest.raises(ValidationError):plan(hook_title=text)


@pytest.mark.parametrize('reference',[False,True])
def test_headline_never_changes_webcam_geometry(reference):
    from rezak.framing import video_filter
    from rezak.plan import Segment
    s=Segment(start_ms=0,end_ms=8000,framing='split',region=Region(x=0.0,y=0.0,w=.25,h=.4),secondary_region=Region(x=.25,y=0.0,w=.75,h=1.0))
    assert video_filter('[in]','out',s,720,1280,1920,1080,headline_ms=5000,reference=reference)==video_filter('[in]','out',s,720,1280,1920,1080,headline_ms=0,reference=reference)


def test_headline_never_moves_background_stack():
    from rezak.backgrounds import stack_filter
    s=plan().segments[0]
    assert stack_filter('[in]','out',s,720,1280,1920,1080,headline_ms=5000)==stack_filter('[in]','out',s,720,1280,1920,1080,headline_ms=0)

def test_screen_interaction_does_not_become_face_only(monkeypatch):
    import numpy as np
    from rezak import framing
    monkeypatch.setattr(framing,'frame',lambda *a:np.zeros((540,960,3),dtype=np.uint8))
    monkeypatch.setattr(framing,'detect',lambda *a:(Region(x=.02,y=.02,w=.2,h=.3),None))
    p=framing.auto_frame(plan(),'fixture','reaction')
    assert p.segments[0].framing=='split'
    assert p.segments[0].secondary_region==Region(x=0.0,y=0.0,w=1.0,h=1.0)
