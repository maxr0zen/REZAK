"""Prompt-directed re-selection within one clip and its nearby source context."""
import json
import os
from pathlib import Path
from .analysis import BonsaiAdapter,sha_file,windows
from .boundaries import finish_boundary
from .plan import EditPlan
from .media import source_path
from .events import emit
from .clips import ClipLibrary

def refine(request,root,adapter=None,render_output=True):
    root=Path(root).resolve();base=EditPlan.model_validate(request['plan'])
    source=source_path(root,base.source_id);digest=sha_file(source)
    transcript=None
    for file in sorted((root/'transcripts').glob(base.source_id+'-*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
        candidate=json.loads(file.read_text(encoding='utf-8'))
        if candidate.get('source_sha256')==digest:transcript=candidate;break
    if transcript is None:raise ValueError('Нет расшифровки этой записи. Сначала выполните обычную обработку исходника.')
    if not os.environ.get('BONSAI_MODEL_REVISION'):raise ValueError('BONSAI_MODEL_REVISION не задана')
    instruction=request['instruction'].strip()
    if not 3<=len(instruction)<=1500:raise ValueError('Задание должно содержать от 3 до 1500 символов')
    directory=root/'analysis'/base.source_id/('edit-'+request['job_id']);directory.mkdir(parents=True,exist_ok=True)
    cached=directory/'plan.json'
    audit=directory/'request.json'
    previous=json.loads(audit.read_text(encoding='utf-8')) if audit.exists() else {}
    can_resume=cached.exists() and previous.get('instruction')==instruction and previous.get('source_sha256')==digest and previous.get('model_revision')==os.environ['BONSAI_MODEL_REVISION']
    if can_resume:
        plan=EditPlan.model_validate_json(cached.read_text(encoding='utf-8'))
        plan.validate_media(transcript['duration_ms'],[])
        emit('llm',1,'Используется сохранённый проверенный план по вашему заданию')
    else:
        groups=[]
        for cut in base.segments:
            nearby=[s for s in transcript['segments'] if s['end_ms']>max(0,cut.start_ms-15000) and s['start_ms']<cut.end_ms+15000]
            groups.extend(windows(nearby,max_chars=4000))
        adapter=adapter or BonsaiAdapter();selected=[];decisions=[]
        for index,group in enumerate(groups):
            emit('llm',index/max(1,len(groups)),'Доработка по вашему заданию',windows_done=index,windows_total=len(groups))
            decision=adapter.decide(group,directory/f'response-{index}',instruction=instruction)
            decisions.append(decision.model_dump())
            if not decision.keep or decision.external_context_required:continue
            ids=[s['id'] for s in group]
            if decision.start_segment_id not in ids or decision.end_segment_id not in ids:raise ValueError('Модель указала неизвестный эпизод')
            left,right=ids.index(decision.start_segment_id),ids.index(decision.end_segment_id)
            if left>right:raise ValueError('Модель перепутала границы эпизода')
            chosen=group[left:right+1];start=chosen[0]['start_ms']
            try:end=finish_boundary(start,chosen[-1]['end_ms'],transcript)
            except ValueError:continue
            selected.append({'start_ms':start,'end_ms':end,'evidence_refs':[f"asr:segment:{s['id']}" for s in chosen]})
        (directory/'request.json').write_text(json.dumps({**request,'source_sha256':digest,'model_revision':os.environ['BONSAI_MODEL_REVISION'],'decisions':decisions},ensure_ascii=False,indent=2),encoding='utf-8')
        if not selected:raise ValueError('Не найден законченный эпизод под это задание. Исходная нарезка сохранена.')
        # Collapse overlapping windows instead of repeating the same footage.
        merged=[]
        for segment in sorted(selected,key=lambda s:s['start_ms']):
            if merged and segment['start_ms']<=merged[-1]['end_ms']:
                merged[-1]['end_ms']=max(merged[-1]['end_ms'],segment['end_ms'])
            else:merged.append(segment)
        value=base.model_dump();value['segments']=merged
        from .editorial import captions_for
        if base.profile=='vertical':
            value['captions']=captions_for(transcript,merged,word_mode=True)
        else:
            value['captions']=[c.model_dump() for c in base.captions if c.kind=='emphasis' and any(c.start_ms>=cut['start_ms'] and c.end_ms<=cut['end_ms'] for cut in merged)]

        plan=EditPlan.model_validate(value);plan.validate_media(transcript['duration_ms'],[])
        (directory/'plan.json').write_text(plan.model_dump_json(indent=2),encoding='utf-8')
        emit('llm',1,'План доработки по заданию проверен')
    if not render_output:return plan
    from .render import render
    output=render(plan,root)
    library=ClipLibrary(root)
    try:parent=library.metadata(library.path(request['filename']))
    except FileNotFoundError:parent={}
    library.write_metadata(output,{**library.metadata(output),**({'publisher_streamer_id':parent['publisher_streamer_id']} if parent.get('publisher_streamer_id') else {}),'title':request['title'],'parent_clip':request['filename'],'instruction':instruction})
    emit('verify',1,'Копия после доработки проверена')
    return output
