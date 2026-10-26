import argparse
import os
from pathlib import Path
from .plan import EditPlan
from .render import render

def main():
    parser = argparse.ArgumentParser(description="Rezak: validated local video editing")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("render")
    command.add_argument("plan", type=Path)
    command.add_argument("--data", type=Path, default=Path(os.environ.get("REZAK_DATA", "data")))
    analysis = sub.add_parser("analyze")
    analysis.add_argument("source_id")
    analysis.add_argument("--data", type=Path, default=Path(os.environ.get("REZAK_DATA", "data")))
    analysis.add_argument("--render", action="store_true")
    analysis.add_argument('--profile', choices=['both', 'vertical', 'horizontal'], default='both')
    shorts=sub.add_parser('shorts');shorts.add_argument('source_id');shorts.add_argument('--render',action='store_true');shorts.add_argument('--profile',default='vertical');shorts.add_argument('--data',type=Path,default=Path(os.environ.get('REZAK_DATA','data')))
    live=sub.add_parser('live-shorts');live.add_argument('request',type=Path);live.add_argument('--render',action='store_true');live.add_argument('--data',type=Path,default=Path(os.environ.get('REZAK_DATA','data')))
    merge=sub.add_parser('curate');merge.add_argument('request',type=Path);merge.add_argument('--render',action='store_true');merge.add_argument('--profile',default='horizontal');merge.add_argument('--data',type=Path,default=Path(os.environ.get('REZAK_DATA','data')))
    refinement = sub.add_parser('refine')
    refinement.add_argument('request',type=Path)
    refinement.add_argument('--data',type=Path,default=Path(os.environ.get('REZAK_DATA','data')))
    args = parser.parse_args()
    try:
        if args.command=='live-shorts':
            import json
            from .live import analyze
            print(json.dumps(analyze(json.loads(args.request.read_text(encoding='utf-8')),args.data,args.render),ensure_ascii=False));return
        if args.command=='shorts':
            import json
            from .shorts import reselect
            print(json.dumps(reselect(args.source_id,args.data,render_outputs=args.render),ensure_ascii=False));return
        if args.command=='curate':
            import json
            from .merge import merge
            print(merge(json.loads(args.request.read_text(encoding='utf-8')),args.data));return
        if args.command == 'refine':
            import json
            from .refinement import refine
            print(refine(json.loads(args.request.read_text(encoding='utf-8')),args.data))
            return
        if args.command == "analyze":
            import json
            from .analysis import analyze
            print(json.dumps(analyze(args.source_id, args.data, render_outputs=args.render, profile=args.profile),ensure_ascii=False,indent=2))
            return
        plan = EditPlan.model_validate_json(args.plan.read_text(encoding="utf-8-sig"))
        print(render(plan, args.data))
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"Ошибка: {exc}\n")

if __name__ == "__main__":
    main()
