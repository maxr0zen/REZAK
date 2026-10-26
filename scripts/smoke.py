"""Run from the project root: python -m scripts.smoke (development dependencies)."""
import json
import os
from pathlib import Path
import shutil
import imageio_ffmpeg
from rezak.media import probe
from rezak.plan import EditPlan
from rezak.process import run
from rezak.render import render

os.environ.setdefault('FFMPEG',imageio_ffmpeg.get_ffmpeg_exe())
if Path('.tools/ffprobe.exe').exists():
    os.environ.setdefault('FFPROBE',str(Path('.tools/ffprobe.exe').resolve()))
root=Path('data').resolve()
(root/'sources').mkdir(parents=True,exist_ok=True)
source=root/'sources/synthetic.mp4'
if not source.exists():
    run([os.environ['FFMPEG'],'-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=30:duration=6','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=6','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',source])
plan=EditPlan.model_validate_json(Path('examples/manual.json').read_text(encoding='utf-8'))
output=render(plan,root)
run([os.environ['FFMPEG'],'-v','error','-ss','1','-i',output,'-frames:v','1',output.with_suffix('.png')])
print(json.dumps({'output':str(output),'probe':probe(output)},ensure_ascii=False,indent=2))
