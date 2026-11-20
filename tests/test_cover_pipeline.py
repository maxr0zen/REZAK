import json
from types import SimpleNamespace
import pytest
from rezak.cover_pipeline import CoverBrief, validate_brief, queue_cover, process_job, atomic_json

def test_caption_limits_and_evidence():
    brief=CoverBrief(top='ЗА ЭТО',bottom='СТРАЙК?!',evidence_id=4,quote='получил страйк')
    assert validate_brief(brief,[{'id':4,'text':'Он получил страйк за видео'}])['id']==4
    with pytest.raises(ValueError):validate_brief(brief,[{'id':4,'text':'Совсем другой эпизод'}])
    with pytest.raises(ValueError):CoverBrief(top='СО СТРИМА',bottom='ЛУЧШЕЕ',evidence_id=4,quote='получил страйк')

def test_queue_uses_only_selected_complete_segments(tmp_path):
    (tmp_path/'transcripts').mkdir()
    rows=[{'id':1,'start_ms':0,'end_ms':1000,'text':'НЕ ВКЛЮЧАТЬ'},
          {'id':4,'start_ms':2000,'end_ms':3000,'text':'Он получил страйк за видео'}]
    (tmp_path/'transcripts/src-1.json').write_text(json.dumps({'segments':rows}),encoding='utf-8')
    class Adapter:
        base_url='http://test'
        def request(self,request,**kwargs):
            payload=json.loads(request.data)
            assert 'НЕ ВКЛЮЧАТЬ' not in str(payload)
            return json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({
                'top':'ЗА ЭТО','bottom':'СТРАЙК?!','evidence_id':4,'quote':'получил страйк'})}}]})
    plan=SimpleNamespace(profile='horizontal',source_id='src',title='Тест',segments=[SimpleNamespace(start_ms=2000,end_ms=4000)])
    path=queue_cover(tmp_path/'clip.mp4',plan,tmp_path,Adapter())
    job=json.loads(path.read_text());assert job['at_ms']==2500 and job['state']=='pending'
    plan.profile='vertical';assert queue_cover(tmp_path/'short.mp4',plan,tmp_path,Adapter()) is None

def test_failed_render_is_terminal_and_preserves_cover(tmp_path,monkeypatch):
    from rezak import photocraft_cover
    exports=tmp_path/'data/exports';exports.mkdir(parents=True)
    (exports/'clip.mp4').write_bytes(b'video');(exports/'clip.cover.jpg').write_bytes(b'approved')
    path=exports/'clip.cover-job.json'
    atomic_json(path,{'state':'pending','video':'clip.mp4','source_id':'src','brief':{
        'top':'ЗА ЭТО','bottom':'СТРАЙК?!','evidence_id':4,'quote':'получил страйк'}})
    def fail(*a):raise RuntimeError('PhotoCraft unavailable')
    monkeypatch.setattr(photocraft_cover,'build_cover',fail)
    assert process_job(path,tmp_path)
    assert json.loads(path.read_text())['state']=='needs_review'
    assert not process_job(path,tmp_path)
    assert (exports/'clip.cover.jpg').read_bytes()==b'approved'

def test_path_escape_rejected(tmp_path):
    path=tmp_path/'bad.json';atomic_json(path,{'state':'pending','video':'../clip.mp4','source_id':'src'})
    with pytest.raises(ValueError):process_job(path,tmp_path)
