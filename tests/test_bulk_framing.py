import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from rezak.clips import ClipLibrary
from rezak.web import create_app
from rezak.plan import EditPlan,Region
from rezak.framing import stable,detect
from rezak.shorts import Candidate,acceptable
from rezak.shorts import Approval,grounded_approval
from rezak import shorts_rag

def setup(root):
    exports=root/'data/exports';exports.mkdir(parents=True)
    for i in range(3):
        p=exports/f'clip{i}.mp4';p.write_bytes(b'video')
        p.with_suffix('.plan.json').write_text(json.dumps({'schema_version':1,'source_id':'synthetic','profile':'vertical','segments':[{'start_ms':i*1000,'end_ms':i*1000+1000}]}))
        p.with_suffix('.probe.json').write_text(json.dumps({'format':{'duration':'1'},'streams':[{'codec_type':'video','width':720,'height':1280}]}))
    (root/'data/sources').mkdir();(root/'data/sources/synthetic.mp4').write_bytes(b'original')
    return ClipLibrary(root/'data')

def test_batch_validates_every_name_before_moving_and_restores_one_token(tmp_path):
    lib=setup(tmp_path)
    with pytest.raises(FileNotFoundError):lib.delete_many(['clip0.mp4','../bad.mp4'])
    assert len(list(lib.exports.glob('*.mp4')))==3
    result=lib.delete_many(['clip0.mp4','clip1.mp4','clip0.mp4'])
    assert result['copies']==2 and result['selected']==2
    assert len(list(lib.exports.glob('*.mp4')))==1
    lib.restore(result['token']);assert len(list(lib.exports.glob('*.mp4')))==3
    assert (lib.data/'sources/synthetic.mp4').read_bytes()==b'original'

def test_batch_move_failure_rolls_back(tmp_path,monkeypatch):
    lib=setup(tmp_path);original=Path.replace
    def replace(path,target):
        if path.name=='clip1.mp4' and path.parent==lib.exports:raise OSError('busy')
        return original(path,target)
    monkeypatch.setattr(Path,'replace',replace)
    with pytest.raises(OSError):lib.delete_many(['clip0.mp4','clip1.mp4'])
    assert len(list(lib.exports.glob('*.mp4')))==3

def test_legacy_fit_defaults_collapse_but_distinct_crop_is_retained(tmp_path):
    lib=setup(tmp_path);plan=json.loads((lib.exports/'clip0.plan.json').read_text())
    expanded=EditPlan.model_validate(plan).model_dump()
    assert lib.plan_identity(plan)==lib.plan_identity(expanded)
    expanded['segments'][0].update(framing='crop',region={'x':.2,'y':.0,'w':.5,'h':1.0})
    assert lib.plan_identity(plan)!=lib.plan_identity(expanded)

def test_bulk_and_framing_api(tmp_path):
    setup(tmp_path)
    with TestClient(create_app(tmp_path,start_background=False,testing=True),headers={'X-Rezak-Client':'1'}) as c:
        region={'x':.25,'y':.0,'w':.5,'h':1.0}
        response=c.post('/api/clips/clip0.mp4/framing',json={'title':'Крупный план','mode':'crop','region':region})
        assert response.status_code==200,response.text
        assert response.json()['metadata']['edit_plan']['segments'][0]['region']==region
        assert c.post('/api/clips/clip0.mp4/framing',json={'title':'bad','mode':'split','region':region}).status_code==400
        assert c.post('/api/clips/clip0.mp4/framing',json={'title':'bad','mode':'crop','region':{**region,'x':.9}}).status_code==422
        response=c.post('/api/clips/delete-many',json={'filenames':['clip0.mp4','clip1.mp4']})
        assert response.status_code==200 and len(c.get('/api/status').json()['clips'])==1
        assert c.post('/api/trash/'+response.json()['token']+'/restore').status_code==200
        assert len(c.get('/api/status').json()['clips'])==3

def test_framing_stability_and_blank_frame_no_invented_region():
    import numpy as np
    assert detect(np.zeros((540,960,3),dtype=np.uint8))==(None,None)
    assert stable([Region(x=.1,y=.1,w=.2,h=.3)]) is None
    assert stable([Region(x=.1,y=.1,w=.2,h=.3),Region(x=.7,y=.1,w=.2,h=.3)]) is None

def test_corner_webcam_is_not_replaced_by_larger_movie_actor(monkeypatch):
    import cv2
    import numpy as np
    class Detector:
        def detectMultiScale(self,*args,**kwargs):return np.array([[400,100,120,120],[40,20,50,50]])
    monkeypatch.setattr(cv2,'CascadeClassifier',lambda path:Detector())
    face,_=detect(np.zeros((540,960,3),dtype=np.uint8))
    assert face.x<.05 and face.w<.2

def test_embedded_webcam_and_player_preserve_cause_and_reaction(monkeypatch):
    import numpy as np
    from rezak import framing
    webcam=Region(x=.02,y=.02,w=.2,h=.3);screen=Region(x=.3,y=.2,w=.6,h=.6)
    monkeypatch.setattr(framing,'frame',lambda *args:np.zeros((540,960,3),dtype=np.uint8))
    monkeypatch.setattr(framing,'detect',lambda image:(webcam,screen))
    plan=EditPlan(schema_version=1,source_id='synthetic',profile='vertical',segments=[{'start_ms':0,'end_ms':10000}])
    result=framing.auto_frame(plan,Path('unused'),'speaker')
    assert result.segments[0].framing=='split'
    assert result.segments[0].region.model_dump()==pytest.approx(webcam.model_dump())
    assert result.segments[0].secondary_region.model_dump()==pytest.approx(screen.model_dump())

def test_strict_short_and_retrieved_reference_is_grounded():
    c=Candidate(start_segment_id=0,end_segment_id=1,hook_strength=4,pace=4,setup_seconds=2,standalone=True,reason='Конкретная смешная развязка')
    assert acceptable(c,20000) and not acceptable(c,60000)
    assert acceptable(c.model_copy(update={'hook_strength':3,'pace':3,'setup_seconds':4}),20000)
    assert not acceptable(c.model_copy(update={'pace':2}),20000)
    assert not acceptable(c.model_copy(update={'setup_seconds':5}),20000)
    refs=shorts_rag.retrieve('Стример смотрит видео, реакция и шутка')
    assert refs and refs[0]['url'].startswith('https://www.youtube.com/shorts/')
    assert any(card['focus']=='split' for card in refs)
    assert len(shorts_rag.fingerprint())==64

def test_final_gate_rejects_invented_payoff_and_late_hook():
    rows=[{'text':'Внезапный поворот и конкретная смешная развязка','words':[{'start_ms':1000,'end_ms':1600,'text':'Внезапный поворот'},{'start_ms':6000,'end_ms':7000,'text':'конкретная смешная развязка'}]}]
    approval=Approval(keep=True,hook_quote='Внезапный поворот',payoff_quote='конкретная смешная развязка',reason='Проверенный пример')
    assert grounded_approval(approval,rows,1000)
    assert not grounded_approval(approval.model_copy(update={'hook_quote':'конкретная смешная развязка'}),rows,1000)
    assert not grounded_approval(approval.model_copy(update={'payoff_quote':'несуществующая развязка'}),rows,1000)

def test_truncated_editor_response_retries_without_losing_candidates(tmp_path):
    from rezak.shorts import ShortAdapter
    adapter=ShortAdapter();calls=[]
    valid={'keep':True,'hook_quote':'Хороший заход','payoff_quote':'Конкретная развязка','reason':'Понятная шутка'}
    def request(req):
        calls.append(req)
        return json.dumps({'choices':[{'message':{'content':'{"keep":true,"reason":"' if len(calls)==1 else json.dumps(valid,ensure_ascii=False)}}]}).encode()
    adapter.request=request
    result=adapter.approve([],0,tmp_path/'response.json')
    assert result.keep and len(calls)==2
    assert (tmp_path/'response.attempt0.json').exists()

@pytest.mark.skipif(__import__('os').environ.get('REZAK_INTEGRATION')!='1',reason='FFmpeg integration')
@pytest.mark.parametrize('mode',['crop','split'])
def test_real_region_render(mode,tmp_path):
    import shutil
    from rezak.web import configure_tools
    from rezak.render import render
    from rezak.media import probe
    configure_tools(Path.cwd());(tmp_path/'sources').mkdir()
    shutil.copy2('data/sources/synthetic.mp4',tmp_path/'sources/synthetic.mp4')
    region={'x':.25,'y':0.0,'w':.5,'h':1.0}
    plan=EditPlan.model_validate({'schema_version':1,'source_id':'synthetic','profile':'vertical','segments':[{'start_ms':0,'end_ms':1000,'framing':mode,'region':region,'secondary_region':{'x':0.0,'y':0.0,'w':1.0,'h':1.0} if mode=='split' else None}]})
    output=render(plan,tmp_path);video=next(s for s in probe(output)['streams'] if s['codec_type']=='video')
    assert (video['width'],video['height'])==(720,1280)
    assert json.loads(output.with_suffix('.plan.json').read_text())['segments'][0]['framing']==mode
    if mode=='split':
        import cv2
        capture=cv2.VideoCapture(str(output));ok,image=capture.read();capture.release()
        assert ok
        from rezak.framing import reference_layout
        top,gap,_=reference_layout(1280)
        assert image[top+8:top+gap-8].max()<8, 'The subtitle band must contain no source video'
