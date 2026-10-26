import os
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from rezak.web import create_app
from rezak.store import Store
from rezak.twitch import protect

@pytest.fixture
def studio(tmp_path):
    app=create_app(tmp_path, start_background=False, testing=True)
    with TestClient(app, headers={'X-Rezak-Client':'1'}) as client:
        yield client, app.state.store, app


def test_react_entry_and_bundled_assets(studio):
    import re
    client, _, _ = studio
    response = client.get('/')
    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
    assert '/static/app.js' not in response.text
    assets = re.findall(r'(?:src|href)="(/static/react/assets/[^"]+)"', response.text)
    assert any(asset.endswith('.js') for asset in assets)
    assert any(asset.endswith('.css') for asset in assets)
    for asset in assets:
        result = client.get(asset)
        assert result.status_code == 200 and result.content

def test_streamers_persist_and_validate(studio):
    client,store,_=studio
    response=client.post('/api/streamers',json={'login':'https://twitch.tv/Some_Channel'})
    assert response.status_code==200
    streamer=response.json();assert streamer['login']=='some_channel'
    assert client.post('/api/streamers',json={'login':'some_channel'}).status_code==409
    assert client.post('/api/streamers',json={'login':'bad/channel'}).status_code==422
    assert client.patch('/api/streamers/'+streamer['id'],json={'auto_clip':False,'quality':'1080p'}).status_code==200
    restored=Store(store.directory).streamers()[0]
    assert restored['auto_clip'] is False and restored['quality']=='1080p'
    assert client.delete('/api/streamers/'+streamer['id']).status_code==200
    assert store.streamers()==[]

def test_upload_cancel_retry_preserves_source(studio):
    client,store,_=studio
    response=client.post('/api/uploads',files={'file':('../../outside.mp4',b'original-media','video/mp4')},data={'profile':'vertical'})
    assert response.status_code==200
    job=response.json();source=Path(job['input_path'])
    assert source.is_relative_to(store.directory.parent/'imports')
    assert source.read_bytes()==b'original-media' and job['profile']=='vertical'
    assert client.post('/api/jobs/'+job['id']+'/cancel').status_code==200
    assert store.job(job['id'])['status']=='cancelled'
    assert client.post('/api/jobs/'+job['id']+'/retry').json()['status']=='queued'
    assert source.read_bytes()==b'original-media'
    assert client.post('/api/jobs/'+job['id']+'/retry').status_code==409
    assert client.get('/api/jobs/'+job['id']+'/log').status_code==200

@pytest.mark.parametrize('name,content',[('video.exe',b'bad'),('empty.mp4',b'')])
def test_invalid_upload_not_queued(studio,name,content):
    client,store,_=studio
    assert client.post('/api/uploads',files={'file':(name,content)}).status_code==400
    assert store.jobs()==[]
    assert list((store.directory.parent/'imports').iterdir())==[]

def test_local_mutation_protection(studio):
    client,_,_=studio
    assert client.post('/api/queue',json={'paused':True},headers={'X-Rezak-Client':'0'}).status_code==403
    assert client.post('/api/queue',json={'paused':True},headers={'Origin':'https://other.example'}).status_code==403
    assert client.get('/api/status',headers={'Host':'other.example'}).status_code==400
    assert client.post('/api/queue',json={'paused':True}).status_code==200
    assert client.get('/api/status').json()['queue_paused'] is True

def test_progress_monotonic_recovery(studio):
    _,store,_=studio
    job=store.create_job('test','source');key=job['id']
    store.update_job(key,status='running')
    store.event(key,{'stage':'asr','progress':.7,'processed_ms':700})
    first=store.job(key)['progress']
    store.event(key,{'stage':'asr','progress':.2})
    assert store.job(key)['progress']==first
    store.event(key,{'stage':'asr','progress':1})
    assert store.job(key)['progress']==43
    store.event(key,{'stage':'nonsense','progress':1})
    assert store.job(key)['progress']==43
    store.recover()
    assert store.job(key)['status']=='interrupted'
    logs=store.logs(key)
    assert logs[-1]['level']=='warning'
    assert store.logs(key,after=logs[-1]['id'])==[]

@pytest.mark.skipif(os.name!='nt',reason='Windows DPAPI')
def test_secrets_and_failed_verification_atomic(studio,monkeypatch):
    client,store,_=studio
    encrypted=protect('original-secret')
    assert 'original-secret' not in encrypted and protect(encrypted,decrypt=True)=='original-secret'
    store.set_setting('twitch_secret',encrypted);store.set_setting('twitch_client_id','oldid')
    monkeypatch.setattr('rezak.web.httpx.post',lambda *a,**kw:httpx.Response(400))
    result=client.post('/api/settings',json={'client_id':'newid','client_secret':'wrongsecret','verify':True,'poll_interval':30})
    assert result.status_code==400
    assert store.setting('twitch_client_id')=='oldid'
    assert store.setting('twitch_secret')==encrypted
    payload=client.get('/api/settings').json()
    assert payload['secret_saved'] is True and 'original-secret' not in str(payload) and encrypted not in str(payload)

def test_video_ranges_and_short_cover(studio,monkeypatch):
    client,store,_=studio
    export=store.directory.parent/'exports'/'short.mp4';export.write_bytes(b'0123456789')
    calls=[]
    def fake_run(args,**kwargs):
        calls.append(args);Path(args[-1]).write_bytes(b'jpeg')
        return type('Result',(),{'returncode':0})()
    monkeypatch.setattr('rezak.web.subprocess.run',fake_run)
    assert client.get('/api/covers/short.mp4').status_code==200
    assert '-ss' not in calls[0]
    assert client.get('/api/covers/short.mp4').status_code==200 and len(calls)==1
    r=client.get('/api/clips/short.mp4',headers={'Range':'bytes=2-5'})
    assert r.status_code==206 and r.content==b'2345'
    assert client.get('/api/clips/not-found.mp4').status_code==404

def test_twitch_poll_dedup_and_offline(studio,monkeypatch):
    _,store,app=studio
    channel=store.add_streamer('testchannel')
    monitor=app.state.monitor
    monkeypatch.setattr(monitor.client,'configured',lambda:True)
    live=[{'user_login':'testchannel','title':'Live title','id':'broadcast1','viewer_count':42}]
    def get(resource,params):
        if resource=='users':return [{'login':'testchannel','display_name':'TestChannel'}]
        assert ('first','100') in params
        return live
    monkeypatch.setattr(monitor.client,'get',get)
    monkeypatch.setattr('rezak.twitch.threading.Thread.start',lambda self:None)
    monitor.poll();monitor.poll()
    jobs=store.jobs()
    assert len(jobs)==1 and jobs[0]['kind']=='capture'
    assert jobs[0]['metadata']['stream_id']=='broadcast1'
    assert store.streamers()[0]['viewers']==42
    live.clear();monitor.poll()
    assert store.streamers()[0]['status']=='offline'
    assert len(store.jobs())==1
    monitor.capture_threads.clear()

def test_saved_recording_recovery_idempotent(studio):
    client,store,_=studio
    job=store.create_job('capture','tw1',kind='capture')
    store.update_job(job['id'],status='interrupted')
    directory=store.directory.parent/'recordings'/job['id'];directory.mkdir()
    part=directory/'part-0000.ts';part.write_bytes(b'saved recording')
    url='/api/jobs/'+job['id']+'/recover'
    response=client.post(url)
    assert response.status_code==200 and len(response.json()['jobs'])==1
    assert client.post(url).json()['jobs']==[]
    assert part.read_bytes()==b'saved recording'
