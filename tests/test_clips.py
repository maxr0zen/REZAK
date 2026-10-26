import json
import shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from rezak.web import create_app
from rezak.clips import ClipLibrary
from rezak.plan import EditPlan
from rezak.jobs import JobRunner

@pytest.fixture
def library(tmp_path):
    data=tmp_path/'data';(data/'exports').mkdir(parents=True)
    plan={'schema_version':1,'source_id':'synthetic','profile':'vertical','segments':[{'start_ms':0,'end_ms':2000},{'start_ms':4000,'end_ms':6000}],'captions':[{'start_ms':1000,'end_ms':1800,'text':'hello'}]}
    for name in ['one','duplicate']:
        p=data/'exports'/(name+'.mp4');p.write_bytes(b'video')
        p.with_suffix('.plan.json').write_text(json.dumps(plan))
        p.with_suffix('.probe.json').write_text(json.dumps({'format':{'duration':'4'},'streams':[{'codec_type':'video','width':360,'height':640}]}))
    (data/'sources').mkdir();(data/'sources/synthetic.mp4').write_bytes(b'original')
    return ClipLibrary(data),tmp_path

def test_trim_maps_output_time_across_source_gaps(library):
    lib,_=library
    plan=lib.trimmed_plan('one.mp4',1500,3000)
    assert [(s.start_ms,s.end_ms) for s in plan.segments]==[(1500,2000),(4000,5000)]
    captions=list(plan.timeline_captions())
    assert captions[0].start_ms==0 and captions[0].end_ms==300
    for a,b in [(-1,1000),(0,5000),(2000,2100),(2000,1000)]:
        with pytest.raises(ValueError):lib.trimmed_plan('one.mp4',a,b)

def test_delete_duplicates_restore_and_original_unchanged(library):
    lib,_=library
    result=lib.delete('one.mp4')
    assert result['copies']==2 and not list(lib.exports.glob('*.mp4'))
    assert (lib.data/'sources/synthetic.mp4').read_bytes()==b'original'
    assert lib.restore(result['token'])['ok']
    assert len(list(lib.exports.glob('*.mp4')))==2
    with pytest.raises(FileNotFoundError):lib.path('../sources/synthetic.mp4')
    with pytest.raises(FileNotFoundError):lib.restore('../outside')

def test_edit_api_and_persistent_title(library):
    lib,root=library
    app=create_app(root,start_background=False,testing=True)
    with TestClient(app,headers={'X-Rezak-Client':'1'}) as c:
        filename=c.get('/api/status').json()['clips'][0]['filename']
        assert c.patch('/api/clips/'+filename,json={'title':'Мой ролик'}).status_code==200
        assert c.get('/api/status').json()['clips'][0]['title']=='Мой ролик'
        from urllib.parse import unquote
        response=c.get('/api/clips/'+filename+'?download=true')
        assert 'Мой ролик' in unquote(response.headers['content-disposition'])
        assert lib.metadata(lib.path(filename))['title_origin']=='manual'
        assert c.patch('/api/clips/'+filename,json={'title':'  '}).status_code==422
        r=c.post('/api/clips/'+filename+'/trim',json={'title':'Короткая копия','start_ms':1000,'end_ms':3000})
        assert r.status_code==200
        job=r.json();assert job['kind']=='clip_edit' and job['status']=='queued'
        assert len(job['metadata']['edit_plan']['segments'])==2
        assert c.post('/api/clips/'+filename+'/trim',json={'title':'bad','start_ms':1000,'end_ms':9000}).status_code==400
        prompt=c.post('/api/clips/'+filename+'/refine',json={'title':'Prompt copy','instruction':'Продли конец до завершения мысли'})
        assert prompt.status_code==200 and prompt.json()['kind']=='clip_refine'
        assert prompt.json()['metadata']['parent_clip']==filename
        deleted=c.delete('/api/clips/'+filename)
        assert deleted.status_code==200 and c.get('/api/status').json()['clips']==[]
        assert c.post('/api/trash/'+deleted.json()['token']+'/restore').status_code==200
        assert c.get('/api/status').json()['clips'][0]['title']=='Мой ролик'

@pytest.mark.skipif(__import__('os').environ.get('REZAK_INTEGRATION')!='1',reason='FFmpeg integration')
def test_edit_job_real_render(tmp_path):
    root=Path.cwd();data=tmp_path/'data';(data/'sources').mkdir(parents=True)
    shutil.copy2(root/'data/sources/synthetic.mp4',data/'sources/synthetic.mp4')
    from rezak.store import Store
    from rezak.web import configure_tools
    from rezak.media import probe,ffmpeg
    from rezak.process import run
    configure_tools(root)
    store=Store(data/'app');runner=JobRunner(store,tmp_path)
    plan=EditPlan.model_validate({'schema_version':1,'source_id':'synthetic','profile':'vertical','segments':[{'start_ms':1000,'end_ms':2000}],'captions':[]})
    job=store.create_job('Edited fixture','synthetic',kind='clip_edit',profile='vertical',metadata={'edit_plan':plan.model_dump(),'parent_clip':'fixture.mp4'})
    runner.process(job);result=store.job(job['id']);assert result['status']=='done',result
    output=data/'exports'/result['exports'][0]
    assert abs(float(probe(output)['format']['duration'])-1)<.15
    run([ffmpeg(),'-v','error','-xerror','-i',output,'-f','null','-'],timeout=60)
    assert ClipLibrary(data).metadata(output)['title']=='Edited fixture'
    assert result['stages']['render']['progress']==1
