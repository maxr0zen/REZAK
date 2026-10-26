import json
from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient
from rezak.store import Store
from rezak.web import create_app
from rezak.backgrounds import select_background
from rezak.plan import EditPlan


def test_independent_streamer_adhd_settings_survive_restart_and_active_capture(tmp_path):
    with TestClient(create_app(tmp_path,start_background=False,testing=True),headers={'X-Rezak-Client':'1'}) as c:
        a=c.post('/api/streamers',json={'login':'mock_alpha','adhd_mode':True}).json()
        b=c.post('/api/streamers',json={'login':'mock_beta'}).json()
        store=Store(tmp_path/'data/app')
        assert store.streamers()[0]['adhd_mode'] is True
        job=store.create_job('MOCK capture','mock',kind='capture',metadata={'streamer_id':a['id']})
        store.update_job(job['id'],status='recording')
        assert c.patch('/api/streamers/'+a['id'],json={'adhd_mode':False}).status_code==200
        assert c.patch('/api/streamers/'+b['id'],json={'adhd_mode':True}).status_code==200
        restored=Store(tmp_path/'data/app').streamers()
        assert [s['adhd_mode'] for s in restored]==[False,True]
        assert store.job(job['id'])['status']=='recording'


def test_job_snapshot_disables_global_background_without_affecting_other_source(tmp_path):
    from rezak.jobs import JobRunner
    store=Store(tmp_path/'data/app');sources=tmp_path/'data/sources';sources.mkdir()
    runner=JobRunner(store,tmp_path)
    runner.prepare=lambda *args:None
    runner.execute=lambda *args,**kwargs:None
    (tmp_path/'data/exports').mkdir()
    for source,enabled in [('alpha',False),('beta',True)]:
        job=store.create_job('MOCK '+source,source,metadata={'adhd_mode':enabled})
        runner.process(job)
        assert json.loads((sources/(source+'.presentation.json')).read_text())['adhd_mode']==enabled
    # Disabled source never needs to read the library, even when globally enabled.
    p=EditPlan(schema_version=1,source_id='alpha',profile='vertical',segments=[{'start_ms':0,'end_ms':1000}])
    assert select_background(p,tmp_path/'data') is None


def test_live_windows_snapshot_current_channel_setting(tmp_path,monkeypatch):
    from rezak import live
    store=Store(tmp_path/'data/app');s=store.add_streamer('mock_live',adhd_mode=True)
    job=store.create_job('MOCK capture','mock',kind='capture',metadata={'login':s['login'],'streamer_id':s['id']})
    store.update_job(job['id'],status='recording')
    directory=tmp_path/'recording';directory.mkdir()
    parts=[{'file':f'live-{i:06d}.ts','start_ms':i*120000,'end_ms':(i+1)*120000} for i in range(2)]
    monkeypatch.setattr(live,'closed_parts',lambda _:parts)
    monkeypatch.setattr(live,'run',lambda args,**kw:Path(args[-1]).write_bytes(b'mock'))
    monkeypatch.setattr(live,'probe',lambda _: {'format':{'duration':'240'}})
    windows=live.LiveWindows(SimpleNamespace(store=store,runner=SimpleNamespace(data=tmp_path/'data')),job['id'],directory)
    windows.pump()
    store.update_streamer(s['id'],adhd_mode=False)
    parts.append({'file':'live-000002.ts','start_ms':240000,'end_ms':360000})
    windows.pump()
    jobs=[j for j in store.jobs() if j['kind']=='video']
    assert [j['metadata']['adhd_mode'] for j in reversed(jobs)]==[True,False]
    for j in jobs:
        request=json.loads((tmp_path/'data/live/requests'/j['metadata']['live_request']).read_text())
        assert request['adhd_mode']==j['metadata']['adhd_mode']


def test_reference_crop_fills_panels_and_places_subtitles_between_them(tmp_path):
    from rezak.framing import video_filter,reference_layout
    from rezak.subtitles import write_ass
    p=EditPlan(schema_version=1,source_id='mock',profile='vertical',segments=[{'start_ms':0,'end_ms':2000,'framing':'split','region':{'x':0.0,'y':0.0,'w':.25,'h':.4},'secondary_region':{'x':.25,'y':0.0,'w':.75,'h':1.0}}],captions=[{'start_ms':0,'end_ms':1000,'text':'Проверка'}])
    filters=';'.join(video_filter('[in]','out',p.segments[0],720,1280,1920,1080,reference=True))
    top,gap,bottom=reference_layout(1280)
    assert (top,gap,bottom)==(448,80,752)
    assert filters.count('force_original_aspect_ratio=increase')==2
    assert f'crop=720:{bottom}' in filters
    path=tmp_path/'subtitles.ass';write_ass(p,path,reference=True)
    assert f'\\pos(540,{round((top+gap/2)*1.5)})' in path.read_text(encoding='utf-8')


def test_reference_content_crop_prefers_consistent_face_over_center(monkeypatch):
    import numpy as np
    from rezak import framing
    from rezak.plan import Region
    p=EditPlan(schema_version=1,source_id='mock',profile='vertical',segments=[{'start_ms':0,'end_ms':2000,'framing':'split','region':{'x':0.0,'y':0.0,'w':.25,'h':.4},'secondary_region':{'x':.25,'y':0.0,'w':.75,'h':1.0}}])
    monkeypatch.setattr(framing,'frame',lambda *args:np.zeros((1080,1920,3),dtype=np.uint8))
    monkeypatch.setattr(framing,'detect',lambda image:(Region(x=.05,y=.2,w=.2,h=.3),None))
    r=framing.reference_regions(p,'mock',1920,1080).segments[0].secondary_region
    assert r.x==.25 and r.w<.75
    assert r.y==0 and r.h==1
