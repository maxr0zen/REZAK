"""Prompt-directed re-selection within one clip and its nearby source context."""
import json
import os
import urllib.request
from pathlib import Path
from typing import Literal
from .analysis import BonsaiAdapter,sha_file,windows
from .boundaries import finish_boundary
from .plan import EditPlan, StrictModel
from .model_json import parse
from .media import source_path
from .events import emit
from .clips import ClipLibrary

class EditIntent(StrictModel):
    change_timing: bool
    composition: Literal['keep', 'fit', 'speaker', 'screen', 'reaction']


def interpret_edit(adapter, instruction):
    prompt = (
        'Classify the requested edit. Return only JSON with change_timing (boolean) and '
        'composition (keep, fit, speaker, screen, reaction). Change timing only for an explicit '
        'request to trim, extend or reorder footage. Composition alone keeps the exact timestamps. '
        'fit means show the full original frame. speaker means one portrait of the streamer, '
        'including requests to remove a duplicate face or remove the lower panel. screen means '
        'prioritize screen content. reaction means separate webcam and screen content when detected. '
        'keep means no change to framing. All options preserve 9:16 output.'
    )
    payload = {'model':'bonsai2', 'messages':[{'role':'system','content':prompt},
               {'role':'user','content':instruction}], 'response_format':{'type':'json_object'},
               'temperature':0, 'max_tokens':150, 'chat_template_kwargs':{'enable_thinking':False}}
    request = urllib.request.Request(adapter.base_url+'/v1/chat/completions',
                                      data=json.dumps(payload).encode(),
                                      headers={'Content-Type':'application/json'})
    response = json.loads(adapter.request(request))
    return parse(response['choices'][0]['message']['content'], EditIntent)


def apply_composition(plan, source, composition):
    from .framing import auto_frame
    segments = [segment.model_copy(update={'framing':'fit', 'region':None,
                'secondary_region':None, 'framing_note':''}) for segment in plan.segments]
    plan = plan.model_copy(update={'segments':segments})
    focus = 'portrait' if composition == 'speaker' else composition
    return plan if composition == 'fit' else auto_frame(plan, source, focus)

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
    intent = None if can_resume or adapter is not None or base.profile != 'vertical' else interpret_edit(BonsaiAdapter(), instruction)
    if can_resume:
        plan=EditPlan.model_validate_json(cached.read_text(encoding='utf-8'))
        plan.validate_media(transcript['duration_ms'],[])
        emit('llm',1,'Используется сохранённый проверенный план по вашему заданию')
    elif intent is not None and not intent.change_timing:
        if intent.composition == 'keep':
            raise ValueError('Уточните компоновку: один крупный план, полный кадр или вебка и экран.')
        plan = apply_composition(base, source, intent.composition)
        plan.validate_media(transcript['duration_ms'], [])
        audit.write_text(json.dumps({**request, 'source_sha256':digest,
                         'model_revision':os.environ['BONSAI_MODEL_REVISION'],
                         'intent':intent.model_dump()}, ensure_ascii=False, indent=2), encoding='utf-8')
        cached.write_text(plan.model_dump_json(indent=2), encoding='utf-8')
        emit('llm',1,'Компоновка по заданию подготовлена')
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

        plan=EditPlan.model_validate(value)
        if intent is not None and intent.composition != 'keep':
            plan = apply_composition(plan, source, intent.composition)
        plan.validate_media(transcript['duration_ms'],[])
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
