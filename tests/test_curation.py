import json
from pathlib import Path
import os
import pytest
from rezak.plan import EditPlan
from rezak.curation import Rating,choose,combine,target_duration,trim_stream_opening
from rezak.shorts import Candidate,acceptable

def p(start,length):return EditPlan(schema_version=1,source_id='synthetic',profile='horizontal',segments=[{'start_ms':start,'end_ms':start+length}])
def r(i,score=4,**kw):return Rating(id=i,interest=score,coherence=4,novelty=4,reason='Содержательный эпизод с понятным развитием',**kw)

def test_select_best_near_half_hour_and_drop_low_quality():
    plans=[p(i*600000,600000) for i in range(12)]
    ratings=[r(i,5 if i in (1,5,8) else 2) for i in range(12)]
    assert choose(plans,ratings,1800000)==[1,5,8]
    final=combine([plans[i] for i in [1,5,8]])
    assert sum(s.end_ms-s.start_ms for s in final.segments)==1800000
    assert target_duration(8387000)==1800000

def test_dependency_includes_setup_and_stays_in_budget():
    plans=[p(i*300000,300000) for i in range(4)]
    selected=choose(plans,[r(0,2),r(1,5,requires_previous=True),r(2,4),r(3,2)],600000)
    assert selected==[0,1]


def test_stream_edit_excludes_technical_blocks_even_as_dependencies():
    plans = [p(i * 300000, 300000) for i in range(4)]
    ratings = [r(0, 5, discard=True), r(1, 5, requires_previous=True), r(2), r(3)]
    assert choose(plans, ratings, 1200000) == [2, 3]


def test_full_episode_does_not_force_ninety_minute_or_highlight_budget(tmp_path):
    from rezak.curation import curate
    class Editor:
        def rank(self, items):
            return [r(i['id'], 2, discard=i['id']==0) for i in items]
    plans = [p(i*1800000, 1800000) for i in range(6)]
    chosen, report = curate(plans, {'duration_ms':10800000, 'segments':[]}, tmp_path,
                            adapter=Editor(), stream_edit=True)
    assert len(chosen) == 5
    assert report['selected_ms'] == 150*60000


def test_stream_opening_cuts_at_the_selected_transcript_boundary():
    class Editor:
        def opening(self, rows):
            return 2

    transcript = {'segments': [
        {'id': 1, 'start_ms': 1000, 'end_ms': 3500, 'text': 'Подождите, настраиваю звук.'},
        {'id': 2, 'start_ms': 4000, 'end_ms': 6500, 'text': 'Обсудим итоги конкурса.'},
    ]}
    plan = trim_stream_opening(p(1000, 10000), transcript, Editor())
    assert plan.segments[0].start_ms == 4000
    assert plan.segments[0].end_ms == 11000

def test_shorts_ordinary_and_exceptional_limits():
    c=Candidate(start_segment_id=0,end_segment_id=1,hook_strength=3,pace=2,setup_seconds=5,standalone=True,reason='Понятная шутка')
    assert not acceptable(c,23000) and not acceptable(c,45000)
    strong=c.model_copy(update={'exceptional':True,'hook_strength':5,'pace':4,'setup_seconds':2})
    assert acceptable(strong,23000)
    assert acceptable(strong,119000) and not acceptable(strong,121000)
    assert not acceptable(c.model_copy(update={'standalone':False}),10000)

def test_model_json_fence_is_allowed_but_surrounding_prose_is_not():
    from rezak.model_json import parse
    from rezak.shorts import Selection
    assert parse('```json\n{"shorts": []}\n```',Selection).shorts==[]
    with pytest.raises(ValueError):parse('Here is JSON: {"shorts": []}',Selection)

@pytest.mark.skipif(os.environ.get('REZAK_INTEGRATION')!='1',reason='FFmpeg integration')
def test_real_lossless_curated_merge_and_gallery_replacement(tmp_path):
    import shutil
    from rezak.web import configure_tools,create_app
    from rezak.render import render
    from rezak.merge import merge
    from rezak.analysis import sha_file
    from rezak.media import probe
    from fastapi.testclient import TestClient
    configure_tools(Path.cwd());root=tmp_path/'data';(root/'sources').mkdir(parents=True);source=root/'sources/synthetic.mp4';shutil.copy2('data/sources/synthetic.mp4',source)
    outputs=[render(p(i*2000,1000),root) for i in range(3)]
    (root/'transcripts').mkdir();(root/'transcripts/synthetic-one.json').write_text(json.dumps({'source_sha256':sha_file(source),'duration_ms':6000,'segments':[]}),encoding='utf-8')
    output=merge({'filenames':[x.name for x in outputs],'job_id':'fixture','target_ms':1800000},root)
    assert abs(float(probe(output)['format']['duration'])-3)<.2
    assert all(x.exists() for x in outputs)
    with TestClient(create_app(tmp_path,start_background=False,testing=True)) as client:
        assert [c['filename'] for c in client.get('/api/status').json()['clips']]==[output.name]
