"""Generated ASS tags only; transcript text is validated plain text."""
def ass_time(ms):
    centis=round(ms/10);seconds,cs=divmod(centis,100);minutes,s=divmod(seconds,60);hours,m=divmod(minutes,60)
    return f'{hours}:{m:02}:{s:02}.{cs:02}'

def visible_captions(plan):
    captions=list(plan.timeline_captions())
    if plan.profile=='horizontal':
        # Also protects old cached plans and prompt/manual edits with full speech captions.
        total=sum(s.end_ms-s.start_ms for s in plan.segments)
        selected=[];budget=int(total*.01);last=-1200000
        for caption in sorted(captions,key=lambda c:c.start_ms):
            duration=caption.end_ms-caption.start_ms
            if caption.kind=='emphasis' and duration<=6000 and duration<=budget and caption.start_ms-last>=1200000:
                selected.append(caption);budget-=duration;last=caption.start_ms
        return selected
    return sorted(captions,key=lambda c:c.start_ms)

def write_ass(plan,path,source_size=None,background=False,reference=False):
    vertical=plan.profile=='vertical';width,height=(1080,1920) if vertical else (1920,1080)
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,DejaVu Sans,{104 if vertical else 72},{'&H0000E8FF' if vertical else '&H00FFFFFF'},&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,-1,0,1,{10 if vertical else 5},2,2,90,90,{360 if vertical else 100},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    captions=visible_captions(plan);events=[];groups=[];group=[]
    if vertical:
        return write_vertical(plan,path,header,captions,source_size,background,reference)
    for caption in captions:
        if group and (not vertical or caption.kind!='word' or group[-1].kind!='word' or len(group)>=3 or sum(len(c.text.strip())+1 for c in group)+len(caption.text.strip())>26 or caption.start_ms-group[-1].end_ms>400):
            groups.append(group);group=[]
        group.append(caption)
    if group:groups.append(group)
    for group in groups:
        for index,caption in enumerate(group):
            pieces=[]
            for item in group:
                text=item.text.replace('\n',' ').strip()
                color='&H005BCEF5&' if vertical and item is caption else '&H00FFFFFF&'
                pieces.append('{\\c'+color+'}'+text)
            text=' '.join(pieces);characters=sum(len(c.text.strip())+1 for c in group)
            size=min(72,max(30,int((900 if vertical else 1600)/max(1,characters)/.6)))
            tags='{\\fs'+str(size)+('\\fscx104\\fscy104\\t(0,80,\\fscx100\\fscy100)' if vertical else '\\fad(80,120)')+'}'
            end=caption.end_ms
            if index+1<len(group):end=min(group[index+1].start_ms,end+100)
            if round(end/10)>round(caption.start_ms/10):events.append(f'Dialogue: 0,{ass_time(caption.start_ms)},{ass_time(end)},Main,,0,0,0,,{tags}{text}')
    path.write_text(header+'\n'.join(events)+'\n',encoding='utf-8')
    return bool(events)

def write_vertical(plan,path,header,captions,source_size=None,background=False,reference=False):
    """Large burned-in reference style; real ASR phrase timing, no fake words."""
    groups=[];group=[]
    for caption in captions:
        chars=sum(len(c.text.strip())+1 for c in group)+len(caption.text.strip())
        if group and (caption.kind!='word' or group[-1].kind!='word' or len(group)>=3 or chars>18 or caption.start_ms-group[-1].start_ms>800 or caption.start_ms-group[-1].end_ms>350 or group[-1].text.rstrip().endswith(('.', '!', '?', '…', ','))):
            groups.append(group);group=[]
        group.append(caption)
    if group:groups.append(group)
    events=[];offsets=[];offset=0
    if plan.hook_title:
        import textwrap
        lines=textwrap.wrap(plan.hook_title.upper(),width=25,break_long_words=True,break_on_hyphens=False)
        text=r'\N'.join(lines)
        size=min(60,max(24,int(110/max(1,len(lines)))))
        duration=min(5000,sum(s.end_ms-s.start_ms for s in plan.segments))
        tags='{\\an8\\pos(540,96)\\fs'+str(size)+'\\c&H00FFFFFF&\\bord5\\shad2\\b900}'
        events.append(f'Dialogue: 2,0:00:00.00,{ass_time(duration)},Main,,0,0,0,,{tags}{text}')
    for segment in plan.segments:
        offsets.append((offset,offset+segment.end_ms-segment.start_ms,segment));offset=offsets[-1][1]
    for index,items in enumerate(groups):
        start=items[0].start_ms;end=items[-1].end_ms
        if index+1<len(groups):end=min(groups[index+1][0].start_ms,end+150)
        text=' '.join(c.text.replace('\n',' ').strip().upper() for c in items)
        # Explicit placement avoids the face in the upper reaction panel and platform UI.
        segment=next((segment for left,right,segment in offsets if left<=start<right),None)
        split=segment is not None and segment.framing=='split'
        from .framing import split_layout
        top,gap,_=split_layout(1920)
        y=top+gap//2 if split else 1460
        if split and source_size:
            from .framing import continuation_layout
            top,gap,_,_=continuation_layout(segment,720,1280,*source_size)
            y=round((top+gap/2)*1.5)
        caption_limit=104
        if split and reference and not background:
            from .framing import reference_layout
            top,gap,_=reference_layout(1280)
            y=round((top+gap/2)*1.5)
            caption_limit=round(gap*1.5*.7)
        if background and source_size:
            from .backgrounds import stack_layout
            top_offset,content,band,_,_=stack_layout(segment,720,1280,*source_size)
            if split:
                top,gap,_,_=continuation_layout(segment,720,content,*source_size)
                y=round((top_offset+top+gap/2)*1.5)
                caption_limit=max(28,round(gap*1.5*.70))
            else:
                y=round((top_offset+content+band/2)*1.5)
        size=min(86 if split else 104,max(54,int(900/max(1,len(text))/.65)))
        size=min(size,caption_limit)
        tags='{\\an5\\pos(540,'+str(y)+')\\fs'+str(size)+'\\b900\\bord10\\shad2\\fscx105\\fscy105\\t(0,70,\\fscx100\\fscy100)}'
        if round(end/10)>round(start/10):events.append(f'Dialogue: 0,{ass_time(start)},{ass_time(end)},Main,,0,0,0,,{tags}{text}')
    path.write_text(header+'\n'.join(events)+'\n',encoding='utf-8')
    return bool(events)
