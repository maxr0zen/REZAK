import json
from pathlib import Path
import pytest
from rezak.analysis import BonsaiAdapter, Decision, analyze, sha_file, windows
from rezak.editorial import Review,StorySpan,ShortSpan


def segment(i, text='Рассказ с началом и концом.'):
    return {'id': i, 'start_ms': i*10000, 'end_ms': (i+1)*10000,
            'text': text, 'words': []}


def test_windows_make_progress_with_overlap():
    rows = [segment(i) for i in range(25)]
    groups = list(windows(rows))
    assert len(groups) < len(rows)
    assert {s['id'] for g in groups for s in g} == set(range(25))
    assert all(g[-1]['end_ms']-g[0]['start_ms'] <= 90000 for g in groups)


def test_oversized_segment_is_explicit_error():
    with pytest.raises(ValueError, match='context budget'):
        list(windows([segment(0, 'x'*5001)]))


@pytest.mark.parametrize('keep,external,count', [(True,False,2),(False,False,0),(True,True,0)])
def test_analysis_plans_and_empty_result(tmp_path,monkeypatch,keep,external,count):
    monkeypatch.setenv('BONSAI_MODEL_REVISION','test-sha/runtime-v1')
    sources=tmp_path/'sources'; sources.mkdir()
    source=sources/'test.mp4'; source.write_bytes(b'test media identity')
    transcripts=tmp_path/'transcripts'; transcripts.mkdir()
    (transcripts/'test-cache.json').write_text(json.dumps({
        'source_sha256':sha_file(source),'duration_ms':20000,
        'segments':[segment(0),segment(1)]}),encoding='utf-8')
    class FakeAdapter:
        calls=0
        def review(self,group,previous,diagnostics):
            self.calls+=1
            if not keep or external:return Review(long_form=[],shorts=[])
            return Review(long_form=[StorySpan(activity='История',summary='Факты',start_segment_id=0,end_segment_id=1,continues_previous=False,continues_next=False)],
                          shorts=[ShortSpan(start_segment_id=0,end_segment_id=1,hook_strength=5,pace=5,setup_seconds=1,standalone=True,reason='Завершённая история')])
    adapter=FakeAdapter()
    result=analyze('test',tmp_path,adapter)
    assert len(result['plans'])==count
    assert result['status']==('selected' if count else 'insufficient_suitable_moments')
    analyze('test',tmp_path,adapter)
    assert adapter.calls==1
    source.write_bytes(b'changed source')
    with pytest.raises(ValueError,match='No transcript'):
        analyze('test',tmp_path,adapter)


def test_model_json_retry_and_evidence_validation(tmp_path,monkeypatch):
    import io
    replies=[{'keep':True,'start_segment_id':999,'end_segment_id':999,
              'reason':'invalid ids','external_context_required':False},
             {'keep':True,'start_segment_id':0,'end_segment_id':1,
              'reason':'complete story','external_context_required':False}]
    calls=[]
    def request(req,timeout):
        calls.append(json.loads(req.data))
        answer=replies.pop(0)
        return io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(answer)}}]}).encode())
    monkeypatch.setattr('urllib.request.urlopen',request)
    result=BonsaiAdapter('http://model:8080').decide([segment(0),segment(1)],tmp_path/'reply')
    assert result.keep and result.end_segment_id==1
    assert len(calls)==2
    assert (tmp_path/'reply.attempt0.json').exists()
    assert calls[0]['chat_template_kwargs']=={'enable_thinking':False}


def test_model_connection_loss_recovers_same_request(tmp_path,monkeypatch):
    import io
    import http.client
    requests=[]
    class Healthy(io.BytesIO):
        status=200
    answer={'keep':False,'start_segment_id':0,'end_segment_id':1,'reason':'Нет эпизода','external_context_required':False}
    def request(req,timeout):
        if isinstance(req,str):return Healthy(b'{"status":"ok"}')
        requests.append(req.data)
        if len(requests)==1:raise http.client.RemoteDisconnected('model stopped')
        return io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(answer)}}]}).encode())
    monkeypatch.setattr('urllib.request.urlopen',request)
    monkeypatch.setattr('rezak.analysis.time.sleep',lambda seconds:None)
    decision=BonsaiAdapter('http://model:8080').decide([segment(0),segment(1)],tmp_path/'reply')
    assert not decision.keep
    assert len(requests)==2 and requests[0]==requests[1]


def test_model_repeated_connection_loss_is_bounded(tmp_path,monkeypatch):
    import io
    import http.client
    calls=[]
    class Healthy(io.BytesIO):status=200
    def request(req,timeout):
        if isinstance(req,str):return Healthy()
        calls.append(1)
        raise http.client.RemoteDisconnected('model stopped')
    monkeypatch.setattr('urllib.request.urlopen',request)
    monkeypatch.setattr('rezak.analysis.time.sleep',lambda seconds:None)
    with pytest.raises(RuntimeError,match='after recovery'):
        BonsaiAdapter('http://model:8080').decide([segment(0)],tmp_path/'reply')
    assert len(calls)==2


def test_short_selection_does_not_force_neighboring_backstory(tmp_path,monkeypatch):
    monkeypatch.setenv('BONSAI_MODEL_REVISION','test-sha/runtime-v1')
    (tmp_path/'sources').mkdir()
    source=tmp_path/'sources/test.mp4'; source.write_bytes(b'fixture')
    (tmp_path/'transcripts').mkdir()
    (tmp_path/'transcripts/test-cache.json').write_text(json.dumps({
        'source_sha256':sha_file(source),'duration_ms':30000,
        'segments':[segment(0),segment(1),segment(2)]}),encoding='utf-8')
    class Adapter:
        def review(self,group,previous,diagnostics):
            return Review(long_form=[],shorts=[ShortSpan(start_segment_id=1,end_segment_id=2,hook_strength=5,pace=5,setup_seconds=0,standalone=True,reason='punchline')])
    result=analyze('test',tmp_path,Adapter())
    plan=json.loads(Path(result['plans'][0]).read_text(encoding='utf-8'))
    assert plan['segments'][0]['start_ms']==10000
    assert plan['segments'][0]['end_ms']==30000
    assert plan['segments'][0]['evidence_refs']==['asr:segment:1','asr:segment:2']
