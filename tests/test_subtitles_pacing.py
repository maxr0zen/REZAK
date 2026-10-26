from pathlib import Path
import json
import os
import pytest
from rezak.plan import EditPlan
from rezak.subtitles import visible_captions,write_ass
from rezak.pacing import tighten

def plan(profile='vertical',duration=5000,captions=None):
    return EditPlan(schema_version=1,source_id='synthetic',profile=profile,segments=[{'start_ms':0,'end_ms':duration}],captions=captions or [])

def words():return [{'start_ms':200,'end_ms':800,'text':'Первое','kind':'word'},{'start_ms':3200,'end_ms':3800,'text':'Второе','kind':'word'}]

def test_horizontal_suppresses_legacy_speech_and_caps_exceptional_duty():
    value=plan('horizontal',duration=600000,captions=[{'start_ms':0,'end_ms':1000,'text':'Обычная речь'},
        {'start_ms':5000,'end_ms':8000,'text':'Развязка','kind':'emphasis','reason':'Неожиданная развязка всей истории'},
        {'start_ms':10000,'end_ms':13000,'text':'Ещё одна','kind':'emphasis','reason':'Конкретная неожиданная кульминация'}])
    assert [c.text for c in visible_captions(value)]==['Развязка']
    assert not visible_captions(plan('horizontal',captions=words()))

def test_emphasis_requires_explanation():
    with pytest.raises(ValueError,match='justification'):
        plan('horizontal',captions=[{'start_ms':0,'end_ms':1000,'text':'Текст','kind':'emphasis'}])

def test_word_highlight_uses_real_word_times_and_safe_generated_tags(tmp_path):
    value=plan(captions=[{'start_ms':100,'end_ms':400,'text':'Привет','kind':'word'},{'start_ms':450,'end_ms':800,'text':'мир','kind':'word'}])
    file=tmp_path/'captions.ass';assert write_ass(value,file)
    ass=file.read_text(encoding='utf-8')
    assert '0:00:00.10' in ass and '0:00:00.80' in ass
    assert 'ПРИВЕТ МИР' in ass and '&H0000E8FF' in ass
    assert r'\bord10' in ass and r'\pos(540,1460)' in ass
    assert r'\fs104' in ass

def test_split_captions_use_lower_panel_and_short_phrases(tmp_path):
    value=plan(captions=[{'start_ms':i*250,'end_ms':i*250+200,'text':text,'kind':'word'} for i,text in enumerate(['Это','очень','длинное','предложение','для','экрана'])])
    value.segments[0].framing='split'
    file=tmp_path/'split.ass';write_ass(value,file);ass=file.read_text(encoding='utf-8')
    assert r'\pos(540,921)' in ass
    assert ass.count('Dialogue:')>=3
    assert 'ЭТО ОЧЕНЬ ДЛИННОЕ ПРЕДЛОЖЕНИЕ' not in ass

def test_tightening_requires_both_quiet_audio_and_word_gap():
    value=plan(captions=words())
    assert len(tighten(value,'fixture',detector=lambda *a:[]).segments)==1
    changed=tighten(value,'fixture',detector=lambda *a:[(1000,3000)])
    assert [(s.start_ms,s.end_ms) for s in changed.segments]==[(0,1150),(2850,5000)]
    assert changed.segments[0].end_ms>=800 and changed.segments[1].start_ms<=3200
    assert len(tighten(plan('horizontal',captions=words()),'fixture',detector=lambda *a:pytest.fail('Must not analyze long-form audio')).segments)==1

def test_word_metadata_survives_timeline_remapping():
    changed=tighten(plan(captions=words()),'fixture',detector=lambda *a:[(1000,3000)])
    captions=list(changed.timeline_captions())
    assert captions[1].kind=='word' and captions[1].start_ms==1500

@pytest.mark.skipif(os.environ.get('REZAK_INTEGRATION')!='1',reason='FFmpeg integration')
def test_real_quiet_pause_cut_and_animated_subtitles(tmp_path):
    from rezak.web import configure_tools
    from rezak.media import ffmpeg,probe
    from rezak.process import run
    from rezak.render import render
    configure_tools(Path.cwd());(tmp_path/'sources').mkdir()
    source=tmp_path/'sources/synthetic.mp4'
    run([ffmpeg(),'-v','error','-i',Path('data/sources/synthetic.mp4').resolve(),'-t','4','-af',"volume=volume=0:enable='between(t,1,3)'",'-c:v','copy',source])
    output=render(plan(duration=4000,captions=words()),tmp_path)
    saved=json.loads(output.with_suffix('.plan.json').read_text(encoding='utf-8'))
    assert len(saved['segments'])==2
    assert float(probe(output)['format']['duration'])<3
    assert all(c['kind']=='word' for c in saved['captions'])
