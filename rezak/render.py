import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from .media import ffmpeg, probe, source_path
from .plan import Interval
from .process import run
from .events import emit
from .subtitles import write_ass
from .pacing import tighten

def stamp(ms):
    h, r = divmod(ms, 3600000)
    m, r = divmod(r, 60000)
    s, r = divmod(r, 1000)
    return f"{h:02}:{m:02}:{s:02},{r:03}"

def render(plan, root, cancel=None, progress_base=0, progress_scale=1):
    root = Path(root).resolve()
    source = source_path(root, plan.source_id)
    info = probe(source)
    if not any(s["codec_type"] == "video" for s in info["streams"]):
        raise ValueError("source has no video")
    if not any(s["codec_type"] == "audio" for s in info["streams"]):
        raise ValueError("MVP requires an audio track")
    video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio_stream = next(s for s in info["streams"] if s["codec_type"] == "audio")
    audio_offset = float(audio_stream.get("start_time", 0))-float(video_stream.get("start_time", 0))
    # trim timestamps are relative to the first decoded frame; normalize source PTS first.
    gap_file = source.with_suffix(".gaps.json")
    gaps = [Interval.model_validate(g) for g in json.loads(gap_file.read_text())] if gap_file.exists() else []
    plan.validate_media(round(float(info["format"]["duration"])*1000), gaps)
    if plan.profile=='vertical':
        from .framing import refine_split
        plan=refine_split(plan,source)
    plan=tighten(plan,source,cancel)
    from .backgrounds import select_background, stack_filter, stack_layout
    background = select_background(plan, root)
    background_info = None
    if background:
        background_path, background_credit, background_seed = background
        background_info = probe(background_path)
        if not any(s['codec_type'] == 'video' for s in background_info['streams']):
            raise ValueError('Фоновый файл не содержит видео')
    elif plan.profile=='vertical':
        from .framing import reference_regions
        plan=reference_regions(plan,source,video_stream['width'],video_stream['height'])
    exports = root / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(exports).free < 256*1024*1024:
        raise ValueError("less than 256 MiB free space")
    width, height = (720, 1280) if plan.profile == "vertical" else (1920, 1080)
    expected = sum(s.end_ms-s.start_ms for s in plan.segments)/1000
    emit('render', progress_base, 'Монтаж '+('9:16' if plan.profile == 'vertical' else '16:9'))
    with tempfile.TemporaryDirectory(prefix="render-", dir=exports) as work:
        work = Path(work)
        captions=write_ass(plan,work/'captions.ass',source_size=(video_stream['width'],video_stream['height']),background=bool(background),reference=not bool(background))
        filters, pairs = [], []
        n = len(plan.segments)
        seek_ms=max(0,min(s.start_ms for s in plan.segments)-2000)
        filters += [f"[0:v]setpts=PTS-STARTPTS,split={n}" + "".join(f"[vs{i}]" for i in range(n)), f"[0:a]asetpts=PTS-STARTPTS+({audio_offset})/TB,asplit={n}" + "".join(f"[as{i}]" for i in range(n))]
        if background:
            filters.append(f'[1:v]setpts=PTS-STARTPTS,fps=30,split={n}'+''.join(f'[bg{i}]' for i in range(n)))
        for i, segment in enumerate(plan.segments):
            start, end = (segment.start_ms-seek_ms)/1000, (segment.end_ms-seek_ms)/1000
            from .framing import video_filter
            filters += [f'[vs{i}]trim=start={start}:end={end},setpts=PTS-STARTPTS[cut{i}]']
            elapsed=sum(s.end_ms-s.start_ms for s in plan.segments[:i])
            headline_ms=max(0,5000-elapsed) if plan.hook_title and plan.profile=='vertical' else 0
            if background:
                filters += stack_filter(f'[cut{i}]',f'main{i}',segment,width,height,video_stream['width'],video_stream['height'],headline_ms=headline_ms)
                header,_,_,bottom_y,bottom_height=stack_layout(segment,width,height,video_stream['width'],video_stream['height'])
                position=str(bottom_y)
                filters += [f'[bg{i}]trim=start={elapsed/1000}:duration={end-start},setpts=PTS-STARTPTS,scale={width}:{bottom_height}:force_original_aspect_ratio=increase,crop={width}:{bottom_height},setsar=1[secondary{i}]',
                            f"[main{i}][secondary{i}]overlay=0:'{position}':shortest=1[framed{i}]"]
            else:
                filters += video_filter(f'[cut{i}]',f'framed{i}',segment,width,height,video_stream['width'],video_stream['height'],headline_ms=headline_ms,reference=plan.profile=='vertical')
            filters += [f'[framed{i}]trim=duration={end-start}[v{i}]', f"[as{i}]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,aresample=48000[a{i}]"]
            pairs.append(f"[v{i}][a{i}]")
        filters.append("".join(pairs)+f"concat=n={n}:v=1:a=1[vcat][aout]")
        filters.append('[vcat]ass=captions.ass[vout]' if captions else '[vcat]null[vout]')
        (work / "filter.txt").write_text(";\n".join(filters), encoding="utf-8")
        def progress(line):
            if line.startswith('out_time_us='):
                try:
                    seconds = int(line.split('=', 1)[1])/1000000
                    emit('render', progress_base+progress_scale*min(.95, seconds/max(expected, .001)*.95),
                         'Рендер '+('9:16' if plan.profile == 'vertical' else '16:9'), processed_ms=round(seconds*1000), total_ms=round(expected*1000))
                except ValueError:
                    pass
        input_args=['-ss',str(seek_ms/1000)] if seek_ms else []
        input_args+=['-t',str((max(s.end_ms for s in plan.segments)-seek_ms)/1000+1),'-i',source]
        if background:
            bg_duration=float(background_info['format']['duration'])
            if bg_duration <= 0:
                raise ValueError('Фоновое видео пустое')
            input_args += ['-stream_loop','-1','-ss',str(background_seed % max(1,int(bg_duration))),'-t',str(expected+1),'-i',background_path]
        run([ffmpeg(), "-v", "error", "-nostdin", "-filter_complex_threads", "2", *input_args, "-filter_complex_script", "filter.txt", "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-threads", "4", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-movflags", "+faststart", '-progress', 'pipe:1', "output.mp4"], timeout=max(1800,expected*12), cancel=cancel, cwd=work, on_stdout=progress)
        output = work / "output.mp4"
        result = probe(output)
        video = next(s for s in result["streams"] if s["codec_type"] == "video")
        expected = sum(s.end_ms-s.start_ms for s in plan.segments)/1000
        if (video["width"], video["height"]) != (width,height) or abs(float(result["format"]["duration"])-expected) > 0.15 or not any(s["codec_type"] == "audio" for s in result["streams"]):
            raise ValueError(f"export verification failed: expected {width}x{height}, {expected:.3f}s; got {video['width']}x{video['height']}, {float(result['format']['duration']):.3f}s; audio={any(s['codec_type']=='audio' for s in result['streams'])}; streams={[(s['codec_type'],s.get('start_time'),s.get('duration')) for s in result['streams']]}")
        run([ffmpeg(), "-v", "error", "-xerror", "-i", output, "-f", "null", "-"], timeout=1800, cancel=cancel)
        title_metadata={}
        try:
            from .titling import enrich_title
            if (root/'transcripts').exists():
                emit('render',progress_base+progress_scale*.98,'Подбирается название по содержанию ролика')
            plan,title_metadata=enrich_title(plan,root)
        except (ValueError,RuntimeError,OSError) as exc:
            emit('render',progress_base+progress_scale*.98,'Название по содержанию пока недоступно; сохранено исходное название',title_error=str(exc)[:200])
        destination = exports / f"{plan.source_id}-{uuid.uuid4().hex}.mp4"
        destination.with_suffix(".plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        destination.with_suffix(".probe.json").write_text(json.dumps(result,indent=2), encoding="utf-8")
        os.replace(output, destination)
        if plan.title or background:
            from .clips import ClipLibrary
            ClipLibrary(root).write_metadata(destination,{'title':plan.title,**title_metadata,
                **({'background_credit':{**background_credit,'changes':'Muted; cropped and looped as a secondary panel'}} if background else {})})
        emit('render', progress_base+progress_scale, 'Ролик полностью декодирован и проверен')
        return destination
