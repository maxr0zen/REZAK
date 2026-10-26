import json
import sys
import threading
from pathlib import Path
import pytest
from pydantic import ValidationError
from rezak.plan import EditPlan, Interval
from rezak.media import source_path
from rezak.process import run, ProcessError

@pytest.fixture
def raw():
    return json.loads(Path('examples/manual.json').read_text(encoding='utf-8'))

@pytest.mark.parametrize('changes', [ {'start_ms':-1}, {'start_ms':True}, {'start_ms':0.5}, {'end_ms':0}, {'end_ms':499}, {'command':'whoami'} ])
def test_reject_bad_segment(raw, changes):
    raw['segments'][0].update(changes)
    with pytest.raises(ValidationError): EditPlan.model_validate(raw)

def test_reject_overlap(raw):
    raw['segments'][1]['start_ms']=2000
    with pytest.raises(ValidationError): EditPlan.model_validate(raw)

def test_duration_and_gaps(raw):
    plan=EditPlan.model_validate(raw)
    with pytest.raises(ValueError): plan.validate_media(5000,[])
    with pytest.raises(ValueError): plan.validate_media(6000,[Interval(start_ms=2000,end_ms=3000)])
    plan.validate_media(6000,[Interval(start_ms=2500,end_ms=3500)])

def test_caption_retime(raw):
    plan=EditPlan.model_validate(raw)
    assert [(c.start_ms,c.end_ms) for c in plan.timeline_captions()] == [(0,1800),(2000,4000)]

@pytest.mark.parametrize('text', ['{\\pos(0,0)}','bad\\Ntext','a\x00b'])
def test_caption_injection(raw,text):
    raw['captions'][0]['text']=text
    with pytest.raises(ValidationError): EditPlan.model_validate(raw)

def test_source_boundary(tmp_path):
    with pytest.raises(ValueError): source_path(tmp_path,'../../secret')

def test_process_exit():
    with pytest.raises(ProcessError,match='exit 7'): run([sys.executable,'-c','raise SystemExit(7)'])

def test_timeout():
    with pytest.raises(ProcessError,match='timeout'): run([sys.executable,'-c','import time; time.sleep(5)'],timeout=.1)

def test_cancel():
    cancel=threading.Event(); cancel.set()
    with pytest.raises(ProcessError,match='cancel'): run([sys.executable,'-c','import time; time.sleep(5)'],cancel=cancel)
