"""Remove only verified quiet pauses between timestamped words in vertical edits."""
import re
from .media import ffmpeg
from .process import run

def quiet_intervals(source,start_ms,end_ms,cancel=None):
    output=run([ffmpeg(),'-v','error','-nostdin','-ss',str(start_ms/1000),'-i',source,'-t',str((end_ms-start_ms)/1000),'-vn','-af',
                'silencedetect=noise=-38dB:d=0.65,ametadata=mode=print:file=-','-f','null','-'],timeout=120,cancel=cancel)
    result=[];start=None
    for key,value in re.findall(r'lavfi\.silence_(start|end)=([0-9.]+)',output):
        point=start_ms+round(float(value)*1000)
        if key=='start':start=point
        elif start is not None:result.append((start,point));start=None
    return result

def tighten(plan,source,cancel=None,detector=quiet_intervals):
    if plan.profile!='vertical':return plan
    words=[c for c in plan.captions if c.kind=='word'];cuts=[]
    if not words:return plan
    for segment in plan.segments:
        # A silent facial response or the beat after TTS is part of the reaction.
        if segment.preserve_pauses:
            cuts.append(segment.model_dump());continue
        local=sorted([w for w in words if w.start_ms>=segment.start_ms and w.end_ms<=segment.end_ms],key=lambda w:w.start_ms)
        gaps=[(a.end_ms+120,b.start_ms-120) for a,b in zip(local,local[1:]) if b.start_ms-a.end_ms>=900]
        if not gaps:cuts.append(segment.model_dump());continue
        quiet=detector(source,segment.start_ms,segment.end_ms,cancel)
        removals=[]
        for left,right in gaps:
            for silence_start,silence_end in quiet:
                start=max(left,silence_start+150);end=min(right,silence_end-150)
                if end-start>=500:removals.append((start,end))
        cursor=segment.start_ms
        for start,end in sorted(removals):
            if start<cursor or start-cursor<250 or segment.end_ms-end<250:continue
            cuts.append({**segment.model_dump(),'start_ms':cursor,'end_ms':start});cursor=end
        cuts.append({**segment.model_dump(),'start_ms':cursor})
    if len(cuts)>100:return plan
    value=plan.model_dump();value['segments']=cuts
    return type(plan).model_validate(value)
