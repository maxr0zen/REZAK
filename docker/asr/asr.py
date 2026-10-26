"""Checkpointed, bounded-memory ASR. Container exit releases CUDA memory."""
import argparse
import gc
import hashlib
import itertools
import json
import os
import sys
from pathlib import Path
from huggingface_hub import snapshot_download
from chunks import pcm_windows,owned_rows

REPO='Systran/faster-whisper-small'
REVISION='536b0662742c02347bc0e980a01041f333bce120'
RATE=16000
CHUNK_SECONDS=60
OVERLAP_SECONDS=2

def event(progress,message,**details):
    if os.environ.get('REZAK_PROGRESS')=='1':
        print('[REZAK_EVENT]'+json.dumps({'stage':'asr','progress':progress,'message':message,**details},ensure_ascii=False),flush=True)

def atomic_json(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temporary,path)

def model_path(download=False):
    return snapshot_download(REPO,revision=REVISION,cache_dir='/models',local_files_only=not download,
                             allow_patterns=['config.json','model.bin','tokenizer.json','vocabulary.txt','preprocessor_config.json'])

def audio_metadata(source):
    import av
    with av.open(str(source),metadata_errors='ignore') as container:
        audio=container.streams.audio[0];video=container.streams.video[0]
        audio_start=float(audio.start_time*audio.time_base) if audio.start_time is not None else 0
        video_start=float(video.start_time*video.time_base) if video.start_time is not None else 0
        duration=float(audio.duration*audio.time_base) if audio.duration is not None else float(container.duration or 0)/av.time_base
        return max(1,round((duration+audio_start-video_start)*1000)),round((audio_start-video_start)*1000)

def pcm_blocks(source):
    import av
    # Unlike decode_audio(), never accumulate the whole recording in BytesIO/numpy.
    with av.open(str(source),metadata_errors='ignore') as container:
        resampler=av.AudioResampler(format='s16',layout='mono',rate=RATE)
        for frame in itertools.chain(container.decode(audio=0),[None]):
            if frame is not None:frame.pts=None
            for converted in resampler.resample(frame):
                yield converted.to_ndarray().tobytes()
        del resampler
    gc.collect()

def transcribe(source_id,max_chunks=None,data_root=Path('/data')):
    import re
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',source_id):raise ValueError('Invalid source id')
    data_root=Path(data_root).resolve()
    source=(data_root/'sources'/(source_id+'.mp4')).resolve()
    if not source.is_relative_to((data_root/'sources').resolve()) or not source.is_file():raise ValueError('Source missing in /data/sources')
    event(0,'Проверка записи и сохранённых частей распознавания')
    digest=hashlib.sha256()
    with source.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):digest.update(block)
    device=os.environ.get('REZAK_ASR_DEVICE','cuda')
    compute='int8' if device=='cpu' else 'int8_float16'
    config={'repo':REPO,'revision':REVISION,'device':device,'compute_type':compute,'beam_size':5,'word_timestamps':True,'vad_filter':True,
            'condition_on_previous_text':False,'stage_version':2,'sample_rate':RATE,'chunk_seconds':CHUNK_SECONDS,'overlap_seconds':OVERLAP_SECONDS}
    key=hashlib.sha256(json.dumps([digest.hexdigest(),config],sort_keys=True).encode()).hexdigest()
    directory=data_root/'transcripts';directory.mkdir(parents=True,exist_ok=True)
    output=directory/(source_id+'-'+key+'.json')
    if output.exists():event(1,'Расшифровка взята из кеша');print(output);return
    checkpoints=directory/'checkpoints'/(source_id+'-'+key);checkpoints.mkdir(parents=True,exist_ok=True)
    duration_ms,audio_offset_ms=audio_metadata(source)
    model=None;rows=[];languages={};completed=0;last_end=0
    import numpy as np
    for window in pcm_windows(pcm_blocks(source),RATE,CHUNK_SECONDS,OVERLAP_SECONDS):
        checkpoint=checkpoints/f'chunk-{window.index:05d}.json'
        if checkpoint.exists():
            saved=json.loads(checkpoint.read_text(encoding='utf-8'))
            if saved['core_start']!=window.core_start or saved['core_end']!=window.core_end:raise ValueError('Checkpoint geometry differs from recording')
            message=f'Восстановлена сохранённая часть {window.index+1}'
        else:
            if model is None:
                event(min(.99,window.core_start/RATE*1000/duration_ms),'Загрузка Whisper small на '+device.upper()+'; распознавание частями по 60 секунд')
                print('Loading Whisper small on '+device.upper()+' (bounded windows)',file=sys.stderr,flush=True)
                from faster_whisper import WhisperModel
                model=WhisperModel(model_path(),device=device,compute_type=compute,num_workers=1,cpu_threads=4)
            audio=np.frombuffer(window.pcm,dtype=np.int16).astype(np.float32)/32768.0
            segments,info=model.transcribe(audio,beam_size=5,word_timestamps=True,vad_filter=True,condition_on_previous_text=False)
            def normalized():
                for segment in segments:
                    yield {'start':segment.start,'end':segment.end,'text':segment.text,
                           'words':[{'start':w.start,'end':w.end,'word':w.word,'probability':w.probability} for w in (segment.words or [])]}
            owned=owned_rows(normalized(),window,RATE,audio_offset_ms)
            saved={'index':window.index,'core_start':window.core_start,'core_end':window.core_end,'language':info.language,'segments':owned}
            atomic_json(checkpoint,saved)
            del audio,segments;gc.collect()
            message=f'Сохранена часть {window.index+1} · таймкоды относительно всей записи'
        rows.extend(saved['segments']);languages[saved['language']]=languages.get(saved['language'],0)+sum(len(s['text']) for s in saved['segments'])
        completed+=1;last_end=window.core_end
        processed=max(0,round(window.core_end*1000/RATE)+audio_offset_ms)
        event(min(.99,processed/duration_ms),message,processed_ms=min(duration_ms,processed),total_ms=duration_ms,
              chunks_done=completed,chunks_total=(duration_ms+CHUNK_SECONDS*1000-1)//(CHUNK_SECONDS*1000),segments_done=len(rows))
        if max_chunks is not None and completed>=max_chunks:
            print('Checkpoint verification stopped after requested chunk count; no incomplete transcript published',flush=True)
            return
    if not completed:raise ValueError('Audio decoder returned no samples')
    rows.sort(key=lambda row:(row['start_ms'],row['end_ms']))
    for index,row in enumerate(rows):row['id']=index
    payload={'source_id':source_id,'source_sha256':digest.hexdigest(),'config':config,'language':max(languages,key=languages.get),
             'duration_ms':max(1,round(last_end*1000/RATE)+audio_offset_ms),'segments':rows}
    atomic_json(output,payload)
    event(1,'Расшифровка сохранена',processed_ms=payload['duration_ms'],total_ms=payload['duration_ms'],chunks_done=completed)
    print(output)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['download','transcribe']);parser.add_argument('source_id',nargs='?')
    parser.add_argument('--max-chunks',type=int,help='Diagnostic bounded run; leaves checkpoints but never publishes partial transcript')
    args=parser.parse_args()
    if args.command=='download':
        try:path=model_path()
        except FileNotFoundError:path=model_path(download=True)
        print(path);return
    if not args.source_id:parser.error('source_id required')
    if args.max_chunks is not None and args.max_chunks<1:parser.error('--max-chunks must be positive')
    transcribe(args.source_id,args.max_chunks)

if __name__=='__main__':main()
