import json
import os
from pathlib import Path
from .process import run

def ffmpeg():
    return os.environ.get("FFMPEG", "ffmpeg")

def probe(path):
    return json.loads(run([os.environ.get("FFPROBE", "ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", Path(path).resolve()]))

def source_path(root, source_id):
    base = Path(root).resolve()
    path = (base / "sources" / (source_id + ".mp4")).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError("source missing or outside allowed data directory")
    return path
