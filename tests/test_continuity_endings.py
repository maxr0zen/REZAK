import json
import pytest
from rezak.continuity import complete_bounded_cut,complete_cut,context_rows

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


def test_verified_ending_stops_before_next_topic_without_pause(tmp_path):
    t = transcript()
    ending, following = t['segments'][4:6]
    ending['words'][0]['text'] = 'переиграл в конце'
    following['start_ms'] = following['words'][0]['start_ms'] = 28020
    t['duration_ms'] = following['end_ms'] = following['words'][0]['end_ms'] = 44000
    answer = {'complete': True, 'end_segment_id': ending['id'],
              'end_quote': 'переиграл в конце', 'reason': 'Реакция закончилась перед новой игрой'}
    with pytest.raises(ValueError, match='Нет безопасного завершения'):
        complete_cut(Adapter(answer), cut(), t, tmp_path / 'old')
    fixed, _ = complete_cut(Adapter(answer), cut(), t, tmp_path / 'new', verified_boundary=True)
    assert 28000 <= fixed['end_ms'] < following['start_ms']
    assert 'asr:segment:1026' not in fixed['evidence_refs']

def test_unresolved_context_edge_does_not_silently_approve(tmp_path):
    a=Adapter({'complete':False,'end_segment_id':1022,'end_quote':'Я сам опасность.','reason':'Ответ ещё не завершён'})
    with pytest.raises(ValueError,match='Ending review invalid'):complete_cut(a,cut(),transcript(),tmp_path/'ending')

def test_bounded_ending_keeps_future_dialogue_as_context_only(tmp_path):
    t = transcript()
    answer = {'complete': True, 'end_segment_id': 1023, 'end_quote': 'постучу в дверь',
              'reason': 'Фраза закончена'}
    adapter = Adapter(answer)
    result = complete_bounded_cut(adapter, cut(), t, tmp_path/'bounded.json', max_duration_ms=18000)
    context = json.loads(adapter.payloads[0]['messages'][1]['content'])
    assert context['allowed_end_ids'] == [1023]
    assert context['segments'][-1]['id'] == 1026
    assert 16000 <= result['end_ms'] < 18000
    adapter.answer = {**answer, 'end_segment_id': 1026, 'end_quote': 'Новая игра'}
    with pytest.raises(ValueError, match='outside the allowed clip range'):
        complete_bounded_cut(adapter, cut(), t, tmp_path/'outside.json', max_duration_ms=18000)


def test_duration_limit_does_not_force_complete_episode_to_thirty_seconds():
    from rezak.shorts import Candidate,acceptable
    c=Candidate(start_segment_id=1,end_segment_id=2,hook_strength=3,pace=3,setup_seconds=2,standalone=True,reason='Реакция')
    assert acceptable(c,65000,complete_episode=True)
    assert not acceptable(c,121000,complete_episode=True)


def test_provisional_stimulus_reads_across_window_and_keeps_full_reaction(tmp_path):
    from rezak.shorts import Candidate, candidate_cut
    t = transcript()
    group = t['segments'][:2]
    candidate = Candidate(start_segment_id=1021,end_segment_id=1022,stimulus_segment_id=1022,
                          hook_strength=4,pace=4,setup_seconds=1,standalone=True,reason='Реакция')
    pending = candidate_cut(candidate,group,t,defer_boundary=True)
    answer = {'complete':True,'end_segment_id':1025,'end_quote':'переиграл в конце.',
              'reason':'Реакция закончена перед новой игрой'}
    adapter = Adapter(answer)
    result = complete_bounded_cut(adapter,pending,t,tmp_path/'neighbor.json',
                                  max_duration_ms=45000,stimulus_id=1022)
    assert 28000 <= result['end_ms'] < 30000
    assert result['evidence_refs'] == [f'asr:segment:{i}' for i in range(1021,1026)]
    context = json.loads(adapter.payloads[0]['messages'][1]['content'])
    assert context['stimulus_id'] == 1022
    assert 1022 not in context['allowed_end_ids']


def test_final_episode_review_repairs_opening_and_ending():
    from rezak.shorts import Approval, Candidate, episode_context, reviewed_episode
    t = transcript()
    proposed = {'start_ms':6000,'end_ms':16000,'evidence_refs':['asr:segment:1022','asr:segment:1023']}
    candidate = Candidate(start_segment_id=1022,end_segment_id=1023,hook_strength=4,
                          pace=4,setup_seconds=1,standalone=True,reason='Реакция')
    context = episode_context(t,proposed)
    approval = Approval(keep=True,start_segment_id=1021,end_segment_id=1025,
                        hook_quote='Мне не грозит опасность',payoff_quote='переиграл в конце',reason='Реакция',
                        ending_quote='переиграл в конце',context_complete=True,ending_complete=True)
    fixed = reviewed_episode(approval,context,proposed,t,candidate,45000)
    assert fixed['start_ms']==0 and 28000<=fixed['end_ms']<30000
    assert fixed['evidence_refs']==[f'asr:segment:{i}' for i in range(1021,1026)]
    with pytest.raises(ValueError,match='не подтверждаются'):
        reviewed_episode(approval.model_copy(update={'payoff_quote':'Новая игра'}),context,proposed,t,candidate,45000)


def test_editor_can_stop_at_payoff_before_new_topic_and_padding_is_bounded():
    from rezak.shorts import Approval, Candidate, episode_context, reviewed_episode, pad_episode
    t = transcript()
    proposed = {'start_ms':6000,'end_ms':34000,'evidence_refs':['asr:segment:1022','asr:segment:1026']}
    context = episode_context(t, proposed)
    candidate = Candidate(start_segment_id=1022,end_segment_id=1026,hook_strength=4,
                          pace=4,setup_seconds=1,standalone=True,reason='Реакция')
    answer = Approval(keep=True,start_segment_id=1021,end_segment_id=1025,
                      hook_quote='Мне не грозит опасность',payoff_quote='переиграл в конце',
                      ending_quote='переиграл в конце',context_complete=True,ending_complete=True,reason='Реакция')
    fixed = reviewed_episode(answer,context,proposed,t,candidate,45000)
    assert 28000 <= fixed['end_ms'] < 30000
    assert 'asr:segment:1026' not in fixed['evidence_refs']
    padded = pad_episode(fixed,t['duration_ms'])
    assert padded['start_ms']==0
    assert padded['end_ms']==fixed['end_ms']+500
    assert pad_episode({'start_ms':1000,'end_ms':49900},50000)['end_ms']==50000
    assert pad_episode({'start_ms':1000,'end_ms':3000},50000)['start_ms']==500
    with pytest.raises(ValueError,match='самостоятельное начало'):
        reviewed_episode(answer.model_copy(update={'context_complete':False}),context,proposed,t,candidate,45000)
    with pytest.raises(ValueError,match='Заключительная цитата'):
        reviewed_episode(answer.model_copy(update={'ending_quote':'Просто конец'}),context,proposed,t,candidate,45000)
