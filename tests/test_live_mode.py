import json
from pathlib import Path
from types import SimpleNamespace
import os
import pytest
from fastapi.testclient import TestClient
from rezak.store import Store
from rezak.live import closed_parts,eligible,LiveWindows
from rezak.web import create_app,configure_tools

def test_live_setting_migrates_and_survives_restart(tmp_path):
    store=Store(tmp_path);row=store.add_streamer('example',live_clip=True)
    assert Store(tmp_path).streamers()[0]['live_clip'] is True
    store.update_streamer(row['id'],live_clip=False)
    assert not store.streamers()[0]['live_clip']

def test_live_api_and_active_capture_guard(tmp_path):
    with TestClient(create_app(tmp_path,start_background=False,testing=True),headers={'X-Rezak-Client':'1'}) as c:
        r=c.post('/api/streamers',json={'login':'live_test','live_clip':True})
        assert r.status_code==200,r.text
        row=r.json();assert row['live_clip']
        store=Store(tmp_path/'data/app')
        job=store.create_job('mock capture','live_mock',kind='capture',metadata={'streamer_id':row['id']})
        store.update_job(job['id'],status='recording')
        assert c.patch('/api/streamers/'+row['id'],json={'live_clip':False}).status_code==409
        store.update_job(job['id'],status='done')
        assert c.patch('/api/streamers/'+row['id'],json={'live_clip':False}).status_code==200

def test_only_closed_playlist_entries_are_processed(tmp_path):
    (tmp_path/'live-000000.ts').write_bytes(b'x'*2048)
    (tmp_path/'live-000001.ts').write_bytes(b'x'*2048)
    (tmp_path/'closed.csv').write_text('live-000000.ts,0,120\nlive-000001.ts,120,')
    assert [p['file'] for p in closed_parts(tmp_path)]==['live-000000.ts']

def test_live_waits_for_future_context_and_deduplicates_absolute_times():
    request={'duration_ms':480000,'offset_ms':240000,'final':False}
    assert not eligible({'start_ms':400000,'end_ms':430000},request,[])
    assert not eligible({'start_ms':340000,'end_ms':470000},request,[])
    assert eligible({'start_ms':200000,'end_ms':240000},request,[])
    assert not eligible({'start_ms':200000,'end_ms':240000},request,[{'start_ms':450000,'end_ms':490000}])
    assert eligible({'start_ms':400000,'end_ms':480000},{**request,'final':True},[])

def test_manual_live_connection_without_helix_does_not_fake_channel_status(tmp_path,monkeypatch):
    from rezak.twitch import TwitchMonitor
    store=Store(tmp_path);streamer=store.add_streamer('mock_live',live_clip=True)
    monitor=TwitchMonitor(store,SimpleNamespace())
    monkeypatch.setattr(monitor,'capture',lambda *a:None)
    job=monitor.record(streamer,force=True)
    assert job['metadata']['live_mode'] and job['status']=='recording'
    assert store.streamers()[0]['status']=='waiting'

def test_ledger_recovers_rendered_outputs_after_interrupted_publish(tmp_path,monkeypatch):
    from rezak import live,shorts
    session='a'*32;source='live_'+session[:20]+'_000001'
    exports=tmp_path/'exports';exports.mkdir();requests=tmp_path/'live/requests';requests.mkdir(parents=True)
    output=exports/(source+'-result.mp4');output.write_bytes(b'completed fixture')
    output.with_suffix('.probe.json').write_text('{}')
    output.with_suffix('.plan.json').write_text(json.dumps({'source_id':source,'segments':[{'start_ms':10000,'end_ms':30000}]}))
    request={'source_id':source,'session_id':session,'duration_ms':240000,'offset_ms':120000,'final':False}
    (requests/(source+'.json')).write_text(json.dumps(request))
    def reselect(source,root,render,live):
        assert live['ledger']==[{'start_ms':130000,'end_ms':150000,'export':output.name}]
        return {'exports':[]}
    monkeypatch.setattr(shorts,'reselect',reselect)
    live.analyze(request,tmp_path,render_outputs=True)
    assert (tmp_path/'live'/('ledger-'+session+'.json')).exists()

@pytest.mark.skipif(os.environ.get('REZAK_INTEGRATION')!='1',reason='FFmpeg integration')
def test_continuous_ffmpeg_segmentation_has_monotonic_closed_playlist(tmp_path):
    from rezak.media import ffmpeg
    from rezak.process import run
    configure_tools(Path.cwd())
    run([ffmpeg(),'-v','error','-stream_loop','2','-i',Path('data/sources/synthetic.mp4').resolve(),'-t','10',
         '-map','0:v:0','-map','0:a:0','-c','copy','-f','segment','-segment_time','2',
         '-reset_timestamps','1','-segment_list',tmp_path/'closed.csv','-segment_list_type','csv',tmp_path/'live-%06d.ts'])
    parts=closed_parts(tmp_path)
    assert len(parts)>=2
    assert all(a['end_ms']<=b['start_ms']+5 for a,b in zip(parts,parts[1:]))

@pytest.mark.skipif(os.environ.get('REZAK_INTEGRATION')!='1',reason='FFmpeg integration')
def test_rolling_windows_queue_final_tail_and_do_not_duplicate(tmp_path):
    import shutil
    from rezak.media import ffmpeg,probe
    from rezak.process import run
    configure_tools(Path.cwd());directory=tmp_path/'data/recordings/session';directory.mkdir(parents=True)
    store=Store(tmp_path/'data/app')
    job=store.create_job('MOCK LIVE','live_capture',kind='capture',metadata={'login':'mockchannel'})
    store.update_job(job['id'],status='recording')
    source=Path('data/sources/synthetic.mp4').resolve()
    run([ffmpeg(),'-v','error','-i',source,'-t','2','-c','copy','-f','mpegts',directory/'live-000000.ts'])
    shutil.copy2(directory/'live-000000.ts',directory/'live-000001.ts')
    (directory/'closed.csv').write_text('live-000000.ts,0,2\nlive-000001.ts,2,4\n')
    windows=LiveWindows(SimpleNamespace(store=store,runner=SimpleNamespace(data=tmp_path/'data')),job['id'],directory)
    windows.pump();windows.pump()
    tasks=[j for j in store.jobs() if j['metadata'].get('operation')=='live']
    assert len(tasks)==1
    assert probe(tasks[0]['input_path'])['streams']
    windows.pump(final=True);windows.pump(final=True)
    tasks=[j for j in store.jobs() if j['metadata'].get('operation')=='live']
    assert len(tasks)==2
    assert sum(j['metadata']['final'] for j in tasks)==1
