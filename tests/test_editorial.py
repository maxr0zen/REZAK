import json
import pytest
from rezak.editorial import Review,StorySpan,ShortSpan,assemble_stories,partition,validate_review,analyze,sha_file

def row(i):return {'id':i,'start_ms':i*10000,'end_ms':(i+1)*10000,'text':f'Фраза {i}.','words':[]}
def story(start,end,activity='Обсуждение',linked=False,new=False):
    return StorySpan(activity=activity,new_activity=new,summary='Мысль развивается',start_segment_id=start,end_segment_id=end,continues_previous=linked,continues_next=True)
def cut(start,end):return {'start_ms':start,'end_ms':end,'evidence_refs':['asr:test']}

def test_thought_across_three_windows_preserves_bridge_and_deduplicates_overlap():
    transcript={'duration_ms':240000,'segments':[row(i) for i in range(24)]}
    items=[(story(0,7),cut(0,80000),0),(story(9,15,linked=True),cut(90000,160000),1),(story(14,23,linked=True),cut(140000,240000),2)]
    stories,links=assemble_stories(items,transcript)
    assert len(stories)==1 and len(stories[0]['cuts'])==1
    assert stories[0]['cuts'][0]['start_ms']==0 and stories[0]['cuts'][0]['end_ms']==240000
    assert len(links)==2

def test_different_activities_create_separate_episodes():
    transcript={'duration_ms':200000,'segments':[row(i) for i in range(20)]}
    stories,links=assemble_stories([(story(0,9,'Игра'),cut(0,100000),0),(story(10,19,'Разбор новостей',new=True),cut(100000,200000),1)],transcript)
    assert [s['activity'] for s in stories]==['Игра','Разбор новостей']
    assert not links

def test_title_variation_and_pending_thought_do_not_split_activity():
    transcript={'duration_ms':200000,'segments':[row(i) for i in range(20)]}
    stories,links=assemble_stories([(story(0,8,'Обсуждение игры'),cut(0,90000),0),(story(10,19,'Шутки об игре'),cut(100000,200000),1)],transcript)
    assert len(stories)==1 and stories[0]['cuts'][0]['end_ms']==200000
    assert links[0]['reason']=='previous_open_thought'
    assert 'asr:segment:9' in stories[0]['cuts'][0]['evidence_refs']

def test_long_activity_splits_without_losing_source_time():
    transcript={'segments':[row(i) for i in range(800)]}
    parts=partition([cut(0,8000000)],transcript)
    assert len(parts)==3
    assert sum(s['end_ms']-s['start_ms'] for part in parts for s in part)==8000000
    assert all(sum(s['end_ms']-s['start_ms'] for s in part)<=3600000 for part in parts)
    assert parts[0][-1]['end_ms']==parts[1][0]['start_ms']

def test_review_rejects_hallucinated_and_overlapping_ids():
    with pytest.raises(ValueError,match='outside'):
        validate_review(Review(long_form=[story(0,99)],shorts=[]),[row(0),row(1)])
    with pytest.raises(ValueError,match='overlap'):
        validate_review(Review(long_form=[story(0,1),story(1,2)],shorts=[]),[row(i) for i in range(3)])

def test_profile_independence_strict_shorts_and_checkpoint_context(tmp_path,monkeypatch):
    monkeypatch.setenv('BONSAI_MODEL_REVISION','fixture')
    (tmp_path/'sources').mkdir();source=tmp_path/'sources'/'test.mp4';source.write_bytes(b'test')
    (tmp_path/'transcripts').mkdir()
    transcript={'source_sha256':sha_file(source),'duration_ms':240000,'segments':[row(i) for i in range(24)]}
    (tmp_path/'transcripts'/'test-one.json').write_text(json.dumps(transcript),encoding='utf-8')
    class Adapter:
        calls=[]
        def review(self,group,previous,diagnostics):
            self.calls.append(previous)
            first,last=group[0]['id'],group[-1]['id']
            return Review(long_form=[story(first,last,linked=bool(previous))],shorts=[ShortSpan(start_segment_id=first,end_segment_id=last,hook_strength=3,pace=5,setup_seconds=8,standalone=True,reason='Слишком длинная подводка')])
    adapter=Adapter();result=analyze('test',tmp_path,adapter=adapter)
    plans=[json.loads(open(p,encoding='utf-8').read()) for p in result['plans']]
    assert plans and all(p['profile']=='horizontal' for p in plans)
    assert all(not p['captions'] for p in plans)
    assert sum(s['end_ms']-s['start_ms'] for p in plans for s in p['segments'])==240000
    assert result['continuity_links'] and result['shorts_rejected']
    assert adapter.calls[0]=={} and adapter.calls[1]['activity']=='Обсуждение'
    count=len(adapter.calls);analyze('test',tmp_path,adapter=adapter)
    assert len(adapter.calls)==count
