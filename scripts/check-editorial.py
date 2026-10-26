"""Read-only transcript smoke check; does not render or publish partial plans."""
import argparse
import json
from pathlib import Path
from rezak.editorial import EditorialAdapter,windows,WINDOW_CHARS,WINDOW_OVERHEAD

parser=argparse.ArgumentParser();parser.add_argument('source_id');parser.add_argument('--windows',type=int,default=3);parser.add_argument('--start-window',type=int,default=0)
args=parser.parse_args()
paths=sorted(Path('/data/transcripts').glob(args.source_id+'-*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
transcript=json.loads(paths[0].read_text(encoding='utf-8'))
adapter=EditorialAdapter();previous={}
directory=Path('/data/analysis')/args.source_id/'editorial-check';directory.mkdir(parents=True,exist_ok=True)
for index,group in enumerate(windows(transcript['segments'],max_chars=WINDOW_CHARS,segment_overhead=WINDOW_OVERHEAD)):
    if index<args.start_window:continue
    if index>=args.start_window+args.windows:break
    result=adapter.review(group,previous,directory/f'window-{index}')
    print(json.dumps({'window':index+1,'long_spans':len(result.long_form),'shorts':len(result.shorts),'activities':[s.activity for s in result.long_form],'new_activities':[s.new_activity for s in result.long_form],'continuations':[s.continues_previous for s in result.long_form]},ensure_ascii=False),flush=True)
    if result.long_form:
        tail=result.long_form[-1];previous={'activity':tail.activity,'summary':tail.summary,'continues_next':tail.continues_next,'last_end_ms':group[-1]['end_ms']}
