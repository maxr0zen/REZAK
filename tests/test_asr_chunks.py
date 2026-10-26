import importlib.util
import sys
from array import array
from pathlib import Path
from types import SimpleNamespace, ModuleType

path=Path(__file__).parents[1]/'docker/asr/chunks.py'
spec=importlib.util.spec_from_file_location('asr_chunks_test',path);chunks=importlib.util.module_from_spec(spec);sys.modules[spec.name]=chunks;spec.loader.exec_module(chunks)

def test_checkpoint_resume_does_not_repeat_inference_or_publish_partial_transcript(tmp_path,monkeypatch):
    hub=ModuleType('huggingface_hub');hub.snapshot_download=lambda *a,**kw:'model'
    monkeypatch.setitem(sys.modules,'huggingface_hub',hub)
    monkeypatch.setitem(sys.modules,'chunks',chunks)
    spec=importlib.util.spec_from_file_location('bounded_asr_test',path.with_name('asr.py'))
    service=importlib.util.module_from_spec(spec);spec.loader.exec_module(service)
    class Audio:
        def astype(self,*a):return self
        def __truediv__(self,value):return self
    numpy=ModuleType('numpy');numpy.int16='int16';numpy.float32='float32';numpy.frombuffer=lambda *a,**kw:Audio()
    monkeypatch.setitem(sys.modules,'numpy',numpy)
    calls=[]
    class Model:
        def __init__(self,*a,**kw):pass
        def transcribe(self,*a,**kw):
            calls.append(1)
            word=SimpleNamespace(start=3,end=4,word=' hello',probability=.9)
            return iter([SimpleNamespace(start=3,end=4,text=' hello',words=[word])]),SimpleNamespace(language='en')
    whisper=ModuleType('faster_whisper');whisper.WhisperModel=Model
    monkeypatch.setitem(sys.modules,'faster_whisper',whisper)
    monkeypatch.setattr(service,'audio_metadata',lambda source:(150000,0))
    monkeypatch.setattr(service,'pcm_blocks',lambda source:iter([b'\x00\x00'*(150*16000)]))
    (tmp_path/'sources').mkdir();(tmp_path/'sources'/'test.mp4').write_bytes(b'fixture')
    service.transcribe('test',max_chunks=2,data_root=tmp_path)
    assert len(calls)==2
    assert not list((tmp_path/'transcripts').glob('*.json'))
    assert len(list((tmp_path/'transcripts'/'checkpoints').rglob('chunk-*.json')))==2
    service.transcribe('test',data_root=tmp_path)
    assert len(calls)==3
    import json
    result=json.loads(next((tmp_path/'transcripts').glob('*.json')).read_text(encoding='utf-8'))
    assert result['duration_ms']==150000
    assert [row['start_ms'] for row in result['segments']]==[3000,61000,121000]
    assert [row['id'] for row in result['segments']]==[0,1,2]

def test_bounded_windows_reconstruct_every_core_sample():
    raw=array('h',range(160)).tobytes()
    windows=list(chunks.pcm_windows((raw[i:i+14] for i in range(0,len(raw),14)),sample_rate=10,chunk_seconds=6,overlap_seconds=2))
    assert [(w.start_sample,w.core_start,w.core_end) for w in windows]==[(0,0,60),(40,60,120),(100,120,160)]
    assert all(len(w.pcm)<=100*2 for w in windows)
    restored=[]
    for window in windows:
        values=array('h');values.frombytes(window.pcm)
        restored.extend(values[window.core_start-window.start_sample:window.core_end-window.start_sample])
    assert restored==list(range(160))

def test_stream_does_not_read_entire_input_before_first_result():
    calls=[]
    def blocks():
        for i in range(10000):calls.append(i);yield b'\x00\x00'*10
    windows=chunks.pcm_windows(blocks(),sample_rate=10,chunk_seconds=6,overlap_seconds=2)
    first=next(windows)
    assert len(calls)==8 and len(first.pcm)==160

def test_word_crossing_boundary_is_owned_once_and_not_cut():
    first=chunks.AudioWindow(0,0,0,60,b'')
    second=chunks.AudioWindow(1,40,60,120,b'')
    def segment(left,right):return [{'start':left,'end':right,'text':' word','words':[{'start':left,'end':right,'word':' word','probability':.9}]}]
    assert chunks.owned_rows(segment(5.5,6.5),first,sample_rate=10)==[]
    rows=chunks.owned_rows(segment(1.5,2.5),second,sample_rate=10)
    assert rows[0]['start_ms']==5500 and rows[0]['end_ms']==6500
    assert rows[0]['words'][0]['text']==' word'

def test_source_offset_applies_to_global_word_times():
    window=chunks.AudioWindow(0,0,0,60,b'')
    rows=chunks.owned_rows([{'start':0,'end':1,'text':'text','words':[]}],window,sample_rate=10,audio_offset_ms=-50)
    assert rows[0]['start_ms']==0 and rows[0]['end_ms']==950

def test_no_empty_window_for_exact_boundary_or_empty_audio():
    assert list(chunks.pcm_windows([],sample_rate=10,chunk_seconds=6,overlap_seconds=2))==[]
    windows=list(chunks.pcm_windows([b'\x00\x00'*120],sample_rate=10,chunk_seconds=6,overlap_seconds=2))
    assert len(windows)==2 and windows[-1].core_end==120
