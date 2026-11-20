import json
import io
import urllib.request

import pytest

from rezak.episodes import Episodes, resolve, validate


def test_brief_chat_between_same_game_is_not_an_upload():
    from rezak.episodes import join_interruptions
    def episode(kind, name, start, end):
        return dict(activity_key=(kind, name), watched_video_complete=False,
                    cuts=[dict(start_ms=start, end_ms=end)])
    items = [episode('game','GTA',0,70000), episode('chat','Переписка',70000,100000),
             episode('game','GTA',100000,900000)]
    assert len(join_interruptions(items)) == 1
    assert len(join_interruptions(items)[0]['cuts']) == 3
    items[-1]['activity_key'] = ('game','Minecraft')
    assert len(join_interruptions(items)) == 3


def test_minimax_receives_explicit_reasoning_effort(monkeypatch):
    from rezak.analysis import BonsaiAdapter
    monkeypatch.setenv('REZAK_LLM_PROVIDER', 'minimax')
    monkeypatch.setenv('MINIMAX_API_KEY', 'test-key')
    calls = []
    def request(req, timeout):
        calls.append(json.loads(req.data))
        return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}).encode())
    monkeypatch.setattr('urllib.request.urlopen', request)
    req = urllib.request.Request('http://fixture', data=json.dumps({'messages':[], 'reasoning_effort':'low'}).encode())
    BonsaiAdapter().request(req)
    assert calls[0]['reasoning_effort'] == 'low'


@pytest.mark.parametrize('bounds', [[(0, 0), (2, 2)], [(0, 1), (1, 2)], [(0, 3)], [(0, 1)]])
def test_rejects_missing_duplicate_and_out_of_range_blocks(bounds):
    result = Episodes(episodes=[dict(first=a, last=b, kind='chat', name='Разговор') for a, b in bounds])
    with pytest.raises(ValueError):
        validate(result, 3)


def test_global_episode_owns_brief_interruptions_and_caches_response(tmp_path):
    stories = [dict(activity=name, activity_key=(kind, name), watched_video_complete=False,
                    cuts=[dict(start_ms=i*10000, end_ms=(i+1)*10000)])
               for i, (kind, name) in enumerate([('chat', 'Обсуждение премии'),
                    ('game', 'Показ базы'), ('chat', 'Голосование'),
                    ('game', 'GTA V'), ('chat', 'Ответ зрителю во время игры')])]
    transcript = {'segments': [dict(start_ms=i*10000, text=s['activity']) for i, s in enumerate(stories)]}
    class Adapter:
        base_url = 'http://fixture'
        calls = 0
        def request(self, req):
            self.calls += 1
            return json.dumps({'choices': [{'message': {'content': json.dumps({'episodes': [
                dict(first=0, last=2, kind='chat', name='Премия и голосование'),
                dict(first=3, last=4, kind='game', name='GTA V')]})}}]}).encode()
    adapter = Adapter()
    result = resolve(stories, transcript, tmp_path, adapter)
    assert [len(s['cuts']) for s in result] == [3, 2]
    assert [s['activity_key'][0] for s in result] == ['chat', 'game']
    assert sum(c['end_ms']-c['start_ms'] for s in result for c in s['cuts']) == 50000
    assert resolve(stories, transcript, tmp_path, adapter) == result
    assert adapter.calls == 1
