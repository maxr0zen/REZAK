import json
import pytest
from rezak.continuity import complete_cut,context_rows

def transcript():
    texts=['Мне не грозит опасность Скайлер.','Я сам опасность.',
           'Это я постучу в дверь.','Переиграл.','Бля, переиграл в конце.',
           'Новая игра.']
    return {'duration_ms':50000,'segments':[{'id':1021+i,'start_ms':i*6000,'end_ms':i*6000+4000,
        'text':text,'words':[{'start_ms':i*6000,'end_ms':i*6000+4000,'text':text}]} for i,text in enumerate(texts)]}

class Adapter:
    base_url='http://unused'
    def __init__(self,answer):self.answer=answer;self.payloads=[]
    def request(self,req):
        self.payloads.append(json.loads(req.data))
        return json.dumps({'choices':[{'message':{'content':json.dumps(self.answer,ensure_ascii=False)}}]}).encode()

def cut():return {'start_ms':0,'end_ms':10200,'evidence_refs':['asr:segment:1021','asr:segment:1022']}

def test_actual_failure_pattern_keeps_quote_and_broadcaster_comment(tmp_path):
    a=Adapter({'complete':True,'end_segment_id':1025,'end_quote':'переиграл в конце.','reason':'Реакция закончена, далее новая игра'})
    fixed,audit=complete_cut(a,cut(),transcript(),tmp_path/'ending')
    payload=json.loads(a.payloads[0]['messages'][1]['content'])
    assert payload['proposed_end_id']==1022
    assert 'Мне не грозит опасность' in payload['episode_anchor']
    assert any(r['id']==1026 for r in payload['segments'])
    assert fixed['end_ms']>=28000
    assert fixed['end_ms']<30000
    assert 'asr:segment:1025' in fixed['evidence_refs'] and fixed['preserve_pauses']

def test_cannot_claim_completion_with_invented_quote(tmp_path):
    a=Adapter({'complete':True,'end_segment_id':1025,'end_quote':'Невыдуманная реакция','reason':'Проверка'})
    with pytest.raises(ValueError,match='Ending review invalid'):complete_cut(a,cut(),transcript(),tmp_path/'ending')

def test_unresolved_context_edge_does_not_silently_approve(tmp_path):
    a=Adapter({'complete':False,'end_segment_id':1022,'end_quote':'Я сам опасность.','reason':'Ответ ещё не завершён'})
    with pytest.raises(ValueError,match='Ending review invalid'):complete_cut(a,cut(),transcript(),tmp_path/'ending')

def test_duration_limit_does_not_force_complete_episode_to_thirty_seconds():
    from rezak.shorts import Candidate,acceptable
    c=Candidate(start_segment_id=1,end_segment_id=2,hook_strength=3,pace=3,setup_seconds=2,standalone=True,reason='Реакция')
    assert acceptable(c,65000,complete_episode=True)
    assert not acceptable(c,121000,complete_episode=True)
