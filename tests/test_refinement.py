import json
from pathlib import Path
import pytest
from rezak.boundaries import finish_boundary
from rezak.analysis import Decision,sha_file
from rezak.refinement import refine

def transcript(words,duration=6000):
    return {'duration_ms':duration,'segments':[{'id':0,'start_ms':0,'end_ms':2000,'text':'speech','words':words}]}

def word(start,end,text):return {'start_ms':start,'end_ms':end,'text':text}

def test_finish_whole_word_and_sentence_with_tail():
    t=transcript([word(1500,2200,'unfinished'),word(2300,2600,'ending.'),word(3200,3500,'next')])
    assert finish_boundary(0,2000,t)==2900

def test_tail_never_starts_next_word():
    t=transcript([word(0,1800,'Done.'),word(2000,2300,'Next')])
    assert finish_boundary(0,1800,t)==1900

def test_clamps_at_source_end():
    t=transcript([word(0,2000,'end.')],duration=2000)
    assert finish_boundary(0,2000,t)==2000

def test_rejects_continuous_speech_without_safe_ending():
    t=transcript([word(i*100,(i+1)*100,'word') for i in range(120)],duration=12000)
    with pytest.raises(ValueError):finish_boundary(0,1000,t,max_extra_ms=500)

def test_prompt_is_scoped_and_preserved(tmp_path,monkeypatch):
    monkeypatch.setenv('BONSAI_MODEL_REVISION','test/runtime')
    (tmp_path/'sources').mkdir();source=tmp_path/'sources/test.mp4';source.write_bytes(b'source')
    (tmp_path/'transcripts').mkdir()
    segments=[{'id':i,'start_ms':i*1000,'end_ms':(i+1)*1000,'text':f'word {i}.','words':[word(i*1000+100,(i+1)*1000-100,f'word {i}.')]} for i in range(40)]
    (tmp_path/'transcripts/test-cache.json').write_text(json.dumps({'source_sha256':sha_file(source),'duration_ms':40000,'segments':segments}))
    request={'job_id':'1'*32,'filename':'clip.mp4','title':'Refined','instruction':'Убери вступление и оставь объяснение','plan':{'schema_version':1,'source_id':'test','profile':'vertical','segments':[{'start_ms':18000,'end_ms':20000}],'captions':[]}}
    calls=[]
    class Adapter:
        def decide(self,group,diagnostics,instruction=None):
            calls.append((group,instruction))
            return Decision(keep=True,start_segment_id=18,end_segment_id=19,reason='complete',external_context_required=False)
    plan=refine(request,tmp_path,Adapter(),render_output=False)
    assert calls[0][1]==request['instruction']
    assert min(s['start_ms'] for s in calls[0][0])>=3000
    assert max(s['end_ms'] for s in calls[0][0])<=35000
    assert plan.source_id=='test' and plan.segments[0].start_ms==18000
    assert (tmp_path/'analysis/test'/('edit-'+'1'*32)/'request.json').exists()


def test_near_eof_retains_source_tail_for_asr_uncertainty():
    t=transcript([word(38000,40767,'last word.')],duration=41935)
    assert finish_boundary(0,40767,t)==41935


@pytest.mark.skipif(__import__('os').environ.get('REZAK_INTEGRATION')!='1',reason='FFmpeg integration')
def test_fps_does_not_extend_video_past_selected_audio_tail(tmp_path):
    import shutil
    from rezak.render import render
    from rezak.plan import EditPlan
    from rezak.media import probe
    from rezak.web import configure_tools
    source=Path.cwd()/'data/sources/smoke-story.mp4'
    if not source.exists():pytest.skip('local smoke story fixture not installed')
    (tmp_path/'sources').mkdir();shutil.copy2(source,tmp_path/'sources/smoke-story.mp4')
    configure_tools(Path.cwd())
    plan=EditPlan.model_validate({'schema_version':1,'source_id':'smoke-story','profile':'vertical','segments':[{'start_ms':0,'end_ms':41935}],'captions':[]})
    output=render(plan,tmp_path)
    assert abs(float(probe(output)['format']['duration'])-41.935)<.15
