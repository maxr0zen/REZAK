import json
import os
from contextvars import ContextVar

progress_sink = ContextVar("progress_sink",default=None)


def emit(stage, progress=None, message='', **details):
    event={'stage':stage,'progress':progress,'message':message,**details}
    sink=progress_sink.get()
    if sink is not None:
        sink(event)
    elif os.environ.get('REZAK_PROGRESS') == '1':
        print('[REZAK_EVENT]'+json.dumps({'stage': stage, 'progress': progress, 'message': message, **details}, ensure_ascii=False), flush=True)
