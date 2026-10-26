import json
import time
from pathlib import Path
from urllib.parse import parse_qs,urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from rezak.web import create_app
from rezak.twitch import protect


@pytest.fixture
def studio(tmp_path):
    app=create_app(tmp_path,start_background=False,testing=True)
    with TestClient(app,headers={'X-Rezak-Client':'1'}) as c:
        p=app.state.publishing;s=app.state.store
        a=s.add_streamer('mock_alpha');b=s.add_streamer('mock_beta')
        yield c,p,s,a,b


def account(p,key,platform='youtube',remote=None):
    p.store.execute('INSERT INTO publishing_accounts VALUES (?,?,?,?,?,?,1)',
                    (key,platform,remote or key,'MOCK '+key,protect(json.dumps({'access_token':'private-token','refresh_token':'private-refresh'})),time.time()+3600))
    return key


def clip(p,s,owner,name='clip.mp4',size=20):
    path=p.data/'exports'/name;path.write_bytes(b'x'*size)
    path.with_suffix('.plan.json').write_text(json.dumps({'schema_version':1,'source_id':Path(name).stem,'profile':'vertical','segments':[{'start_ms':0,'end_ms':1000}]}))
    path.with_suffix('.probe.json').write_text(json.dumps({'format':{'duration':'1'},'streams':[{'codec_type':'video','width':720,'height':1280}]}))
    if owner:s.create_job('MOCK',Path(name).stem,metadata={'streamer_id':owner})
    return path


def test_routes_reject_cross_streamer_and_mixed_batch_is_atomic(studio):
    c,p,s,a,b=studio
    account(p,'alpha');account(p,'beta')
    p.bind(a['id'],'youtube','alpha');p.bind(b['id'],'youtube','beta')
    path=clip(p,s,a['id'])
    assert c.put('/api/publishing/routes/'+a['id']+'/youtube',json={'account_id':'beta'}).status_code==400
    payload={'filename':path.name,'account_ids':['alpha','beta'],'title':'MOCK','privacy':'private','made_for_kids':False}
    assert c.post('/api/publishing/jobs',json=payload).status_code==400
    assert p.snapshot()['jobs']==[]
    payload['account_ids']=['alpha']
    assert c.post('/api/publishing/jobs',json=payload).status_code==200
    assert c.post('/api/publishing/jobs',json=payload).status_code==400
    snapshot=c.get('/api/status').json()['publishing']
    assert 'private-token' not in str(snapshot) and 'credentials' not in str(snapshot)


def test_unknown_owner_requires_manual_assignment(studio):
    c,p,s,a,b=studio
    account(p,'alpha');p.bind(a['id'],'youtube','alpha');path=clip(p,s,None)
    assert p.owner(path.name) is None
    assert c.post('/api/publishing/jobs',json={'filename':path.name,'account_ids':['alpha'],'title':'MOCK','privacy':'private','made_for_kids':False}).status_code==400
    assert c.put('/api/publishing/clips/'+path.name+'/owner',json={'streamer_id':a['id']}).status_code==200
    assert p.owner(path.name)==a['id']
    assert c.get('/api/publishing/clips/..%2Foutside.mp4/owner').status_code in (400,404)


def test_old_live_exports_resolve_via_capture_and_do_not_guess_titles(studio):
    c,p,s,a,b=studio
    path=clip(p,s,None)
    capture=s.create_job('A misleading title for beta','old_capture',kind='capture',metadata={'streamer_id':a['id']})
    s.create_job('beta-looking title','clip',metadata={'live_session':capture['id']})
    assert p.owner(path.name)==a['id']


def test_credentials_stay_encrypted_and_cannot_silently_change_apps(studio):
    c,p,s,a,b=studio
    p.configure('youtube','mock-id','mock-secret')
    encrypted=s.setting('publish_youtube_secret')
    assert encrypted!='mock-secret' and protect(encrypted,decrypt=True)=='mock-secret'
    account(p,'alpha')
    assert c.post('/api/publishing/applications/youtube',json={'client_id':'other','client_secret':'new-secret'}).status_code==400
    assert p.config()['youtube']['client_id']=='mock-id'
    assert 'mock-secret' not in c.get('/api/publishing/applications').text


def test_restart_marks_uncertain_jobs_for_manual_review(studio):
    c,p,s,a,b=studio
    account(p,'alpha');p.bind(a['id'],'youtube','alpha');path=clip(p,s,a['id'])
    key=p.enqueue(path.name,['alpha'],'MOCK','','private',False)[0]
    p.update(key,status='uploading',sent=10)
    p.start()
    assert p.snapshot()['jobs'][0]['status']=='attention'
    p.stop()


@pytest.mark.parametrize('platform',['youtube','tiktok'])
def test_oauth_cookie_pkce_scopes_identity_and_single_use(studio,platform):
    import hashlib,base64
    c,p,s,a,b=studio
    assert c.post('/api/publishing/applications/'+platform,json={'client_id':'mock-client','client_secret':'mock-secret'}).status_code==200
    scopes='https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly' if platform=='youtube' else 'user.info.basic,video.upload'
    def handler(request):
        if request.url.path.endswith('token') or request.url.path.endswith('token/'):
            body=parse_qs(request.content.decode());assert body['client_secret']==['mock-secret']
            assert body['code_verifier']
            return httpx.Response(200,json={'access_token':'private-token','refresh_token':'private-refresh','expires_in':3600,'scope':scopes,'open_id':'mock-remote'})
        if platform=='youtube':return httpx.Response(200,json={'items':[{'id':'mock-remote','snippet':{'title':'MOCK verified channel'}}]})
        return httpx.Response(200,json={'data':{'user':{'open_id':'mock-remote','display_name':'MOCK verified TikTok'}},'error':{'code':'ok'}})
    p.client=httpx.Client(transport=httpx.MockTransport(handler))
    begin=c.post('/api/publishing/oauth/'+platform).json();q=parse_qs(urlparse(begin['url']).query)
    state=q['state'][0];row=s.rows('SELECT * FROM publishing_oauth WHERE state=?',(state,))[0]
    verifier=protect(row['verifier'],decrypt=True);digest=hashlib.sha256(verifier.encode()).digest()
    expected=digest.hex() if platform=='tiktok' else base64.urlsafe_b64encode(digest).decode().rstrip('=')
    assert q['code_challenge']==[expected]
    assert c.get('/api/publishing/oauth/'+platform+'/callback',params={'state':'wrong','code':'mock'},follow_redirects=False).status_code==400
    response=c.get('/api/publishing/oauth/'+platform+'/callback',params={'state':state,'code':'mock'},follow_redirects=False)
    assert response.status_code==303,response.text
    assert p.snapshot()['accounts'][0]['remote_id']=='mock-remote'
    assert c.get('/api/publishing/oauth/'+platform+'/callback',params={'state':state,'code':'mock'},follow_redirects=False).status_code==400
    assert 'mock-secret' not in c.get('/api/publishing/applications').text


def test_youtube_upload_is_chunked_with_explicit_privacy_and_owner(studio):
    c,p,s,a,b=studio
    account(p,'alpha');p.bind(a['id'],'youtube','alpha');path=clip(p,s,a['id'],size=8*1024**2+17)
    requests=[]
    def handler(request):
        requests.append(request)
        if request.method=='POST':
            data=json.loads(request.content);assert data['status']=={'privacyStatus':'private','selfDeclaredMadeForKids':False}
            return httpx.Response(200,headers={'Location':'https://www.googleapis.com/upload/mock-session'})
        assert request.headers['authorization']=='Bearer private-token'
        if len(requests)==2:return httpx.Response(308)
        return httpx.Response(200,json={'id':'mock-video-id'})
    p.client=httpx.Client(transport=httpx.MockTransport(handler))
    key=p.enqueue(path.name,['alpha'],'MOCK title','description','private',False)[0]
    job=p.snapshot()['jobs'][0];p.update(key,status='uploading');p.process(job)
    result=p.snapshot()['jobs'][0]
    assert result['status']=='uploaded' and result['sent']==path.stat().st_size
    assert result['result_url']=='https://www.youtube.com/watch?v=mock-video-id'
    assert len(requests)==3
    assert requests[-1].headers['content-range']==f'bytes {8*1024**2}-{path.stat().st_size-1}/{path.stat().st_size}'


def test_tiktok_upload_is_draft_and_waits_for_remote_confirmation(studio):
    c,p,s,a,b=studio
    account(p,'alpha',platform='tiktok');p.bind(a['id'],'tiktok','alpha');path=clip(p,s,a['id'])
    def handler(request):
        if request.url.path.endswith('/init/'):
            assert json.loads(request.content)['source_info']['total_chunk_count']==1
            return httpx.Response(200,json={'data':{'upload_url':'https://open-upload.tiktokapis.com/video/mock','publish_id':'mock-inbox'},'error':{'code':'ok'}})
        if request.url.path.endswith('/fetch/'):
            return httpx.Response(200,json={'data':{'status':'SEND_TO_USER_INBOX'},'error':{'code':'ok'}})
        assert 'authorization' not in request.headers
        return httpx.Response(201)
    p.client=httpx.Client(transport=httpx.MockTransport(handler))
    key=p.enqueue(path.name,['alpha'],'MOCK title','','private',False)[0]
    p.process(p.snapshot()['jobs'][0]);job=p.snapshot()['jobs'][0]
    assert job['status']=='processing' and job['remote_id']=='mock-inbox'
    p.check_tiktok(job)
    assert p.snapshot()['jobs'][0]['status']=='inbox'


def test_uncertain_transfer_never_retries_automatically_and_hides_secrets(studio):
    c,p,s,a,b=studio
    account(p,'alpha');p.bind(a['id'],'youtube','alpha');path=clip(p,s,a['id'])
    def handler(request):
        if request.method=='POST':return httpx.Response(200,headers={'Location':'https://www.googleapis.com/upload/mock-session'})
        raise httpx.ReadError('private-token secret-url')
    p.client=httpx.Client(transport=httpx.MockTransport(handler))
    key=p.enqueue(path.name,['alpha'],'MOCK','','private',False)[0];p.process(p.snapshot()['jobs'][0])
    result=p.snapshot()['jobs'][0];assert result['status']=='attention'
    assert 'private-token' not in str(result) and 'secret-url' not in str(result)
    assert c.post('/api/publishing/jobs/'+key+'/retry').status_code==400
    assert c.post('/api/publishing/jobs/'+key+'/review-retry',json={'confirmed_not_sent':False}).status_code==422
    assert c.post('/api/publishing/jobs/'+key+'/review-retry',json={'confirmed_not_sent':True}).status_code==200
    assert p.snapshot()['jobs'][0]['status']=='queued'


def test_changed_route_stops_queued_upload_before_network(studio):
    c,p,s,a,b=studio
    account(p,'alpha');p.bind(a['id'],'youtube','alpha');path=clip(p,s,a['id'])
    key=p.enqueue(path.name,['alpha'],'MOCK','','private',False)[0]
    p.bind(a['id'],'youtube',None)
    p.client=httpx.Client(transport=httpx.MockTransport(lambda r:pytest.fail('must not send')))
    p.process(p.snapshot()['jobs'][0]);assert p.snapshot()['jobs'][0]['status']=='failed'
    p.retry(key);assert p.snapshot()['jobs'][0]['status']=='queued'
    p.cancel(key);assert p.snapshot()['jobs'][0]['status']=='cancelled'


def test_pending_upload_cannot_lose_file_through_gallery_delete(studio):
    c,p,s,a,b=studio
    account(p,'alpha');p.bind(a['id'],'youtube','alpha');path=clip(p,s,a['id'])
    key=p.enqueue(path.name,['alpha'],'MOCK','','private',False)[0]
    assert c.post('/api/clips/delete-many',json={'filenames':[path.name]}).status_code==400
    assert path.exists()
    p.cancel(key)
    assert c.post('/api/clips/delete-many',json={'filenames':[path.name]}).status_code==200


def test_long_montage_is_not_sent_to_tiktok(studio):
    c,p,s,a,b=studio
    account(p,'alpha',platform='tiktok');p.bind(a['id'],'tiktok','alpha');path=clip(p,s,a['id'])
    info=json.loads(path.with_suffix('.probe.json').read_text());info['format']['duration']='1800'
    path.with_suffix('.probe.json').write_text(json.dumps(info))
    with pytest.raises(ValueError,match='10 минут'):p.enqueue(path.name,['alpha'],'MOCK','','private',False)
    assert p.snapshot()['jobs']==[]


@pytest.mark.parametrize('url',['http://www.googleapis.com/upload','https://evil.example/upload','https://www.googleapis.com.evil.example/upload','https://user@www.googleapis.com/upload'])
def test_upload_hosts_cannot_redirect_secrets(url):
    from rezak.publishing import Publishing
    with pytest.raises(ValueError):Publishing.upload_url(url,'youtube')
