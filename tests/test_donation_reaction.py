import pytest
from rezak.shorts import Candidate, Approval, candidate_cut, grounded_approval


def candidate(**extra):
    return Candidate(start_segment_id=0,end_segment_id=0,hook_strength=4,pace=4,
                     setup_seconds=2,standalone=True,reason='Донат и ответ',**extra)


def transcript():
    return {'duration_ms':20000,'segments':[
        {'id':0,'start_ms':0,'end_ms':3000,'text':'Донат: купи себе мозги!',
         'words':[{'start_ms':0,'end_ms':3000,'text':'Донат: купи себе мозги!'}]},
        {'id':1,'start_ms':6000,'end_ms':9000,'text':'Тогда тебе придётся скинуться первым!',
         'words':[{'start_ms':6000,'end_ms':9000,'text':'Тогда тебе придётся скинуться первым!'}]}]}


def test_reaction_after_pause_extends_donation_cut():
    t=transcript()
    cut=candidate_cut(candidate(stimulus_segment_id=0,reaction_end_segment_id=1),t['segments'],t)
    assert cut['end_ms']>=9000
    assert 'asr:segment:1' in cut['evidence_refs']
    assert cut['preserve_pauses']


@pytest.mark.parametrize('fields',[{'stimulus_segment_id':0},
    {'stimulus_segment_id':0,'reaction_end_segment_id':99},
    {'stimulus_segment_id':1,'reaction_end_segment_id':0}])
def test_missing_or_invalid_reaction_is_not_an_invented_tail(fields):
    t=transcript()
    with pytest.raises(ValueError):candidate_cut(candidate(**fields),t['segments'],t)


def test_donation_gate_requires_reaction_quote_in_clip():
    t=transcript();c=candidate(stimulus_segment_id=0,reaction_end_segment_id=1)
    a=Approval(keep=True,hook_quote='купи себе мозги',payoff_quote='купи себе мозги',
               reason='Ответ',reaction_quote='Тогда тебе придётся скинуться первым')
    assert not grounded_approval(a,t['segments'][:1],0,c)
    assert grounded_approval(a,t['segments'],0,c)
    assert not grounded_approval(a.model_copy(update={'reaction_quote':''}),t['segments'],0,c)
    assert not grounded_approval(a.model_copy(update={'reaction_quote':'купи себе мозги'}),t['segments'],0,c)


def test_reaction_silent_beat_is_not_removed_by_pacing():
    from rezak.plan import EditPlan
    from rezak.pacing import tighten
    t=transcript();cut=candidate_cut(candidate(stimulus_segment_id=0,reaction_end_segment_id=1),t['segments'],t)
    plan=EditPlan(schema_version=1,source_id='test',profile='vertical',segments=[cut],
        captions=[{**w,'kind':'word'} for row in t['segments'] for w in row['words']])
    assert tighten(plan,'fixture',detector=lambda *a:pytest.fail('Reaction pauses must survive')).segments==plan.segments


def test_complete_reaction_may_exceed_thirty_seconds_without_being_cut():
    from rezak.shorts import acceptable
    c=candidate(stimulus_segment_id=0,reaction_end_segment_id=1)
    assert acceptable(c,45000)
    assert not acceptable(c,61000)
    assert not acceptable(candidate(),45000)
