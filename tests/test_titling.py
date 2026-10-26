import io
import json
from pathlib import Path
from rezak.plan import EditPlan
from rezak.analysis import sha_file
from rezak.titling import Title,TitleAdapter,excerpts,enrich_title,download_name

def plan():return EditPlan(schema_version=1,source_id='test',profile='vertical',segments=[{'start_ms':1000,'end_ms':3000}],title='Сильный хук с подводкой')

def test_title_context_excludes_unused_footage_and_partial_segment_words():
    transcript={'segments':[{'id':0,'start_ms':0,'end_ms':4000,'text':'НЕ ВКЛЮЧАТЬ','words':[{'start_ms':0,'end_ms':500,'text':'Чужая тема '},{'start_ms':1200,'end_ms':2000,'text':'Поиск наушников '},{'start_ms':3300,'end_ms':4000,'text':'Другая тема'}]}]}
    assert excerpts(plan(),transcript)==[{'id':0,'text':'Поиск наушников'}]

def test_long_title_samples_start_middle_and_end():
    p=plan().model_copy(update={'profile':'horizontal','segments':EditPlan(schema_version=1,source_id='test',profile='horizontal',segments=[{'start_ms':0,'end_ms':300000}]).segments})
    transcript={'segments':[{'id':i,'start_ms':i*1000,'end_ms':(i+1)*1000,'text':f'Тема {i}'} for i in range(300)]}
    rows=excerpts(p,transcript)
    assert len(rows)==12 and rows[0]['id']==0 and rows[-1]['id']==299

def test_title_cache_and_source_identity(tmp_path):
    (tmp_path/'sources').mkdir();source=tmp_path/'sources/test.mp4';source.write_bytes(b'fixture')
    (tmp_path/'transcripts').mkdir();(tmp_path/'transcripts/test-one.json').write_text(json.dumps({'source_sha256':sha_file(source),'segments':[{'id':1,'start_ms':1000,'end_ms':3000,'text':'Он искал наушники, которые держал в руках.'}]}),encoding='utf-8')
    class Adapter:
        calls=0
        def title(self,rows,profile,hint):
            self.calls+=1
            return Title(title='Искал наушники прямо в руках',evidence_segment_ids=[1])
    adapter=Adapter();p,metadata=enrich_title(plan(),tmp_path,adapter)
    assert p.title=='Искал наушники прямо в руках' and metadata['title_evidence']==[1]
    enrich_title(plan(),tmp_path,adapter);assert adapter.calls==1
    source.write_bytes(b'new source')
    assert enrich_title(plan(),tmp_path,adapter)[0].title==plan().title
    assert adapter.calls==1

def test_model_title_retries_editorial_reason_and_invalid_evidence(monkeypatch):
    calls=[]
    def request(req,timeout):
        calls.append(req)
        if 'fact-check' in json.loads(req.data)['messages'][0]['content']:
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps({'supported':True,'quote':'Искал наушники в руках'})}}]}).encode())
        reply={'title':'Сильный хук про наушники','evidence_segment_ids':[99]} if len(calls)==1 else {'title':'Почему наушники оказались в руках','evidence_segment_ids':[1]}
        return io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(reply)}}]}).encode())
    monkeypatch.setattr('urllib.request.urlopen',request)
    answer=TitleAdapter('http://model').title([{'id':1,'text':'Искал наушники в руках'}],'vertical','reason')
    assert answer.title=='Почему наушники оказались в руках' and len(calls)==3

def test_unsupported_title_is_not_accepted(monkeypatch):
    import pytest
    def request(req,timeout):
        verification='fact-check' in json.loads(req.data)['messages'][0]['content']
        reply={'supported':False,'quote':''} if verification else {'title':'Нашёл наушники в холодильнике','evidence_segment_ids':[1]}
        return io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(reply)}}]}).encode())
    monkeypatch.setattr('urllib.request.urlopen',request)
    with pytest.raises(ValueError,match='unsupported'):
        TitleAdapter('http://model').title([{'id':1,'text':'Проверил холодильник, но наушники держал в руке.'}],'vertical','')

def test_download_filename_is_safe_and_human_readable():
    name=download_name('Почему наушники: в руках? / Ответ','vertical')
    assert name=='Почему наушники в руках Ответ — TikTok.mp4'
    assert not any(c in name for c in '<>:"/\\|?*')
