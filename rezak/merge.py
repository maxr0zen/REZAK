"""Curate already rendered clips and concatenate them without another encode."""
import json
import os
from pathlib import Path
import tempfile
import uuid
from .clips import ClipLibrary
from .plan import EditPlan
from .media import ffmpeg,probe
from .process import run
from .events import emit
from .curation import curate,combine
from .analysis import sha_file

def merge(request,root,cancel=None):
    root=Path(root).resolve();library=ClipLibrary(root);paths=[library.path(name) for name in request['filenames']]
    paths.sort(key=lambda p:EditPlan.model_validate_json(p.with_suffix('.plan.json').read_text(encoding='utf-8')).segments[0].start_ms)
    plans=[EditPlan.model_validate_json(p.with_suffix('.plan.json').read_text(encoding='utf-8')) for p in paths]
    if not plans:raise ValueError('No source clips')
    source_id=plans[0].source_id;digest=sha_file(root/'sources'/(source_id+'.mp4'));transcript=None
    for file in sorted((root/'transcripts').glob(source_id+'-*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
        value=json.loads(file.read_text(encoding='utf-8'))
        if value.get('source_sha256')==digest:transcript=value;break
    if transcript is None:raise ValueError('Current source transcript missing')
    directory=root/'analysis'/source_id/('curate-'+request['job_id']);directory.mkdir(parents=True,exist_ok=True)
    chosen,audit=curate(plans,transcript,directory,target_ms=request.get('target_ms',1800000))
    selected=[paths[plans.index(p)] for p in chosen]
    plan=combine(chosen,request.get('title','Общение с чатом и просмотр видео — лучшие эпизоды'))
    (directory/'selection.json').write_text(json.dumps({**audit,'files':[p.name for p in selected]},ensure_ascii=False,indent=2),encoding='utf-8')
    expected=sum(float(probe(p)['format']['duration']) for p in selected)
    signature=None
    for file in selected:
        info=probe(file);video=next(s for s in info['streams'] if s['codec_type']=='video');audio=next(s for s in info['streams'] if s['codec_type']=='audio')
        current=(video['codec_name'],video['width'],video['height'],video.get('pix_fmt'),video.get('r_frame_rate'),audio['codec_name'],audio.get('sample_rate'),audio.get('channels'))
        if signature is not None and current!=signature:raise ValueError('Clips have incompatible encodings; lossless merge refused')
        signature=current
    with tempfile.TemporaryDirectory(prefix='merge-',dir=library.exports) as temp:
        work=Path(temp);listing=work/'concat.txt';listing.write_text('\n'.join("file '"+p.as_posix().replace("'","'\\''")+"'" for p in selected),encoding='utf-8')
        output=work/'output.mp4';emit('render',0,f'Склейка {len(selected)} лучших эпизодов без повторного кодирования',total_ms=round(expected*1000))
        def progress(line):
            if line.startswith('out_time_us='):
                seconds=int(line.split('=',1)[1])/1000000;emit('render',min(.99,seconds/expected),'Склейка выбранных эпизодов',processed_ms=round(seconds*1000),total_ms=round(expected*1000))
        run([ffmpeg(),'-v','error','-nostdin','-f','concat','-safe','0','-i',listing,'-c','copy','-movflags','+faststart','-progress','pipe:1',output],timeout=1800,cancel=cancel,on_stdout=progress)
        info=probe(output)
        if abs(float(info['format']['duration'])-expected)>max(.25,len(selected)*.05):raise ValueError('Merged duration differs from selected clips')
        emit('render',1,'Склейка готова');emit('verify',None,'Полное декодирование итогового ролика')
        run([ffmpeg(),'-v','error','-xerror','-i',output,'-f','null','-'],timeout=1800,cancel=cancel)
        destination=library.exports/(source_id+'-'+uuid.uuid4().hex+'.mp4')
        destination.with_suffix('.plan.json').write_text(plan.model_dump_json(indent=2),encoding='utf-8');destination.with_suffix('.probe.json').write_text(json.dumps(info,indent=2),encoding='utf-8');os.replace(output,destination)
        library.write_metadata(destination,{'title':plan.title,'title_origin':'manual','merged_from':[p.name for p in selected],'curation_target_ms':audit['target_ms']})
    # Keep every old file recoverable; show the new complete montage in the gallery.
    library.supersede_horizontal(source_id,destination.name)
    emit('verify',1,'Итоговый ролик полностью проверен',total_ms=round(expected*1000));return destination
