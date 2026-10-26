"""Live rolling windows and absolute-time duplicate protection."""
import csv
import json
from pathlib import Path
import time
from .media import ffmpeg,probe
from .process import run

def closed_parts(directory):
    path=Path(directory)/'closed.csv'
    if not path.exists():return []
    parts=[]
    for row in csv.reader(path.read_text(encoding='utf-8').splitlines()):
        if len(row)!=3:continue  # Ignore an incomplete playlist write.
        name=Path(row[0]).name
        if not __import__('re').fullmatch(r'live-\d{6}\.ts',name):continue
        try:start,end=round(float(row[1])*1000),round(float(row[2])*1000)
        except ValueError:continue
        file=Path(directory)/name
        if file.is_file() and file.stat().st_size>1024 and end>start:
            parts.append({'file':name,'start_ms':start,'end_ms':end})
    return parts

def eligible(cut,request,ledger):
    if not request.get('final') and cut['start_ms']>=request['duration_ms']-120000:return False
    if not request.get('final') and cut['end_ms']>request['duration_ms']-15000:return False
    start=cut['start_ms']+request['offset_ms'];end=cut['end_ms']+request['offset_ms']
    return not any(start<r['end_ms'] and end>r['start_ms'] for r in ledger)

class LiveWindows:
    def __init__(self,monitor,job_id,directory):
        self.monitor=monitor;self.store=monitor.store;self.runner=monitor.runner
        self.job_id=job_id;self.directory=Path(directory)
        self.state_path=self.directory/'live-state.json'
        self.state=json.loads(self.state_path.read_text()) if self.state_path.exists() else {'next':1,'final':False}

    def pump(self,final=False):
        parts=closed_parts(self.directory)
        if not parts:return
        job=self.store.job(self.job_id);meta=job['metadata']
        pending=[j for j in self.store.jobs() if j['metadata'].get('live_session')==self.job_id and j['status'] in ('queued','running')]
        limit=100000 if final else max(0,2-len(pending))
        indices=list(range(self.state['next'],len(parts)))[:limit]
        if final and not self.state['final'] and len(parts)-1 not in indices:indices.append(len(parts)-1)
        for index in indices:
            is_final=final and index==len(parts)-1
            first=max(0,index-3);window=parts[first:index+1]
            source_id=f'live_{self.job_id[:20]}_{index:06d}'+('_end' if is_final else '')
            dedupe=f'live:{self.job_id}:{index}:{is_final}'
            if self.store.rows('SELECT id FROM jobs WHERE dedupe=?',(dedupe,)):
                self.state['next']=max(self.state['next'],index+1);continue
            source=self.runner.data/'sources'/(source_id+'.mp4');source.parent.mkdir(parents=True,exist_ok=True)
            listing=self.directory/f'window-{index:06d}.concat'
            # Relative generated filenames only; never insert a user path into concat syntax.
            listing.write_text(''.join("file '"+p['file']+"'\n" for p in window),encoding='utf-8')
            temporary=source.with_suffix('.pending.mp4')
            run([ffmpeg(),'-v','error','-nostdin','-y','-f','concat','-safe','1','-i',listing.resolve(),'-map','0:v:0','-map','0:a:0','-c','copy','-movflags','+faststart',temporary],timeout=120)
            info=probe(temporary);duration=round(float(info['format']['duration'])*1000);temporary.replace(source)
            streamer=next((s for s in self.store.streamers() if s['id']==meta.get('streamer_id')),None)
            adhd_mode=bool((streamer or meta).get('adhd_mode',False))
            request={'source_id':source_id,'session_id':self.job_id,'offset_ms':window[0]['start_ms'],'duration_ms':duration,'final':is_final,'adhd_mode':adhd_mode,'streamer_id':meta.get('streamer_id')}
            requests=self.runner.data/'live/requests';requests.mkdir(parents=True,exist_ok=True)
            request_path=requests/(source_id+'.json');request_path.write_text(json.dumps(request),encoding='utf-8')
            self.store.create_job(f"LIVE · {meta['login']} · окно {index+1}",source_id,input_path=source,profile='vertical',dedupe=dedupe,
                metadata={'operation':'live','live_session':self.job_id,'live_request':request_path.name,'duration_ms':duration,'offset_ms':window[0]['start_ms'],'final':is_final,'adhd_mode':adhd_mode,'streamer_id':meta.get('streamer_id')})
            self.state['next']=max(self.state['next'],index+1)
            if is_final:self.state['final']=True
            temporary_state=self.state_path.with_suffix('.tmp');temporary_state.write_text(json.dumps(self.state),encoding='utf-8');temporary_state.replace(self.state_path)
        latest=self.store.job(self.job_id)['metadata']
        unfinished=[j for j in self.store.jobs() if j['metadata'].get('live_session')==self.job_id and j['status'] in ('queued','running')]
        processed=max((j['metadata'].get('offset_ms',0)+j['metadata'].get('duration_ms',0) for j in self.store.jobs()
            if j['metadata'].get('live_session')==self.job_id and j['status']=='done'),default=0)
        self.store.update_job(self.job_id,metadata={**latest,'live_mode':True,'chunks':parts,'captured_ms':parts[-1]['end_ms'],
            'scheduled_ms':parts[min(len(parts)-1,max(0,self.state['next']-1))]['end_ms'] if self.state['next']>1 else 0,
            'processed_ms':processed,'lag_ms':max(0,parts[-1]['end_ms']-processed),'pending_windows':len(unfinished),
            'backlog_chunks':max(0,len(parts)-self.state['next']),'bytes':sum(p.stat().st_size for p in self.directory.glob('live-*.ts'))},
            detail=f"LIVE · записано частей: {len(parts)} · окон в очереди: {len(unfinished)} · отставание: {max(0,parts[-1]['end_ms']-processed)//1000} с · последние 2 мин ждут развязки")

def analyze(request,root,render_outputs=False):
    from .shorts import reselect
    root=Path(root);ledger_path=root/'live'/('ledger-'+request['session_id']+'.json')
    ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else []
    # Recover committed outputs even if the previous window process stopped
    # after rendering and before publishing its ledger.
    for p in (root/'exports').glob('live_'+request['session_id'][:20]+'_*.mp4'):
        plan_path=p.with_suffix('.plan.json')
        if not plan_path.exists() or not p.with_suffix('.probe.json').exists():continue
        plan=json.loads(plan_path.read_text(encoding='utf-8'))
        prior=root/'live/requests'/(plan['source_id']+'.json')
        if not prior.exists() or any(r.get('export')==p.name for r in ledger):continue
        context=json.loads(prior.read_text(encoding='utf-8'))
        if context.get('session_id')!=request['session_id']:continue
        ledger.append({'start_ms':min(s['start_ms'] for s in plan['segments'])+context['offset_ms'],
                       'end_ms':max(s['end_ms'] for s in plan['segments'])+context['offset_ms'],'export':p.name})
    result=reselect(request['source_id'],root,render_outputs,live={**request,'ledger':ledger})
    if render_outputs:
        for output in result['exports']:commit_output(output,request,ledger)
        ledger_path.parent.mkdir(parents=True,exist_ok=True);tmp=ledger_path.with_suffix('.tmp');tmp.write_text(json.dumps(ledger),encoding='utf-8');tmp.replace(ledger_path)
    return result

def commit_output(output,request,ledger):
    if any(r.get('export')==Path(output).name for r in ledger):return
    plan=json.loads(Path(output).with_suffix('.plan.json').read_text(encoding='utf-8'))
    ledger.append({'start_ms':min(s['start_ms'] for s in plan['segments'])+request['offset_ms'],
                   'end_ms':max(s['end_ms'] for s in plan['segments'])+request['offset_ms'],'export':Path(output).name})
