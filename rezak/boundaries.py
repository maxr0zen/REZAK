"""Conservative source-time boundaries: don't cut through recognized speech."""
import re

BOUNDARY_VERSION=2

def finish_boundary(start,end,transcript,max_extra_ms=8000):
    duration=transcript['duration_ms']
    words=sorted([w for s in transcript['segments'] for w in (s.get('words') or []) if w['end_ms']>w['start_ms']],key=lambda w:w['start_ms'])
    limit=min(duration,end+max_extra_ms)
    # Even a segment timestamp may precede its last word's reported end.
    overlapping=[w for w in words if w['start_ms']<end and w['end_ms']>start]
    if overlapping:end=max(end,max(w['end_ms'] for w in overlapping))
    following=[w for w in words if w['start_ms']>=end]
    for word in following:
        gap=word['start_ms']-end
        last=next((w for w in reversed(words) if w['end_ms']<=end),None)
        ended=last is not None and re.search(r'[.!?…]["»\')\]]*$',last['text'].strip())
        if gap>=600 or ended and gap>=60:
            # Add a tail only within silence: don't start another word.
            return min(duration,end+min(400,gap//2))
        if word['end_ms']>limit:
            raise ValueError('Нет безопасного завершения реплики в пределах 8 секунд')
        end=max(end,word['end_ms'])
        if re.search(r'[.!?…]["»\')\]]*$',word['text'].strip()):
            next_word=next((w for w in words if w['start_ms']>=end and w is not word),None)
            if next_word is None:return duration if duration-end<=1500 else min(duration,end+400)
            if next_word['start_ms']-end>=60:return min(duration,end+min(400,(next_word['start_ms']-end)//2))
    return duration if duration-end<=1500 else min(duration,end+400)
