"""Bounded PCM windows and ownership of overlap words (stdlib only)."""
from dataclasses import dataclass

@dataclass(frozen=True)
class AudioWindow:
    index: int
    start_sample: int
    core_start: int
    core_end: int
    pcm: bytes


def pcm_windows(blocks, sample_rate=16000, chunk_seconds=60, overlap_seconds=2):
    core=round(sample_rate*chunk_seconds);overlap=round(sample_rate*overlap_seconds)
    if core<=0 or overlap<0 or overlap>=core:raise ValueError('Invalid audio window geometry')
    iterator=iter(blocks);buffer=bytearray();base=0;decoded=0;start=0;eof=False;index=0
    while True:
        wanted=start+core+overlap
        while not eof and decoded<wanted:
            try:block=next(iterator)
            except StopIteration:eof=True;break
            if len(block)%2:raise ValueError('PCM block must contain whole int16 samples')
            buffer.extend(block);decoded+=len(block)//2
        if start>=decoded:return
        left=max(0,start-overlap);right=min(decoded,wanted)
        yield AudioWindow(index,left,start,min(start+core,decoded),bytes(buffer[(left-base)*2:(right-base)*2]))
        start+=core;index+=1
        retain=max(0,start-overlap)
        drop=min(len(buffer)//2,max(0,retain-base));del buffer[:drop*2];base+=drop


def owned_rows(segments,window,sample_rate=16000,audio_offset_ms=0):
    offset=window.start_sample*1000/sample_rate+audio_offset_ms
    low=window.core_start*1000/sample_rate+audio_offset_ms
    high=window.core_end*1000/sample_rate+audio_offset_ms
    rows=[]
    for segment in segments:
        words=[]
        raw=segment.get('words') or [{'start':segment['start'],'end':segment['end'],'word':segment['text'],'probability':None}]
        for word in raw:
            left=offset+word['start']*1000;right=offset+word['end']*1000
            if low<=(left+right)/2<high and right>0:
                left=max(0,round(left));right=max(0,round(right))
                if right>left:words.append({'start_ms':left,'end_ms':right,'text':word['word'],'probability':word.get('probability')})
        if words:
            rows.append({'start_ms':words[0]['start_ms'],'end_ms':words[-1]['end_ms'],'text':''.join(w['text'] for w in words),'words':words})
    return rows
