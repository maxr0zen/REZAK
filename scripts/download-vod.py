"""Download a public Twitch VOD using Rezak's isolated recorder container."""
import argparse
import json
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

def download(url,quality='best'):
    match=re.fullmatch(r'https://(?:www\.)?twitch\.tv/videos/([0-9]+)(?:\?[^\s]*)?',url.strip())
    if not match:raise ValueError('Expected https://www.twitch.tv/videos/ID')
    video_id=match[1];url='https://www.twitch.tv/videos/'+video_id
    root=Path(__file__).resolve().parents[1]
    directory=root/'data/recordings'/('vod_'+video_id);directory.mkdir(parents=True,exist_ok=True)
    target=directory/'recording.ts';partial=directory/'recording.part.ts'
    if target.exists():raise ValueError('Recording already downloaded: '+str(target))
    if partial.exists():raise ValueError('An incomplete download exists; preserved at '+str(partial))
    if shutil.disk_usage(directory).free<2*1024**3:raise ValueError('Less than 2 GiB free disk space')
    prefix=['docker','compose','--profile','recorder','run','--rm','-T']
    result=subprocess.run([*prefix,'recorder','--json',url],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=90)
    if result.returncode:raise RuntimeError(result.stderr[-2000:])
    details=json.loads(result.stdout)
    if quality not in details.get('streams',{}):raise ValueError('Quality unavailable: '+quality)
    metadata={**details.get('metadata',{}),'url':url,'quality':quality,'status':'downloading','started':time.time()}
    metadata_file=directory/'metadata.json';metadata_file.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'vod':video_id,'author':metadata.get('author'),'title':metadata.get('title'),'quality':quality},ensure_ascii=True),flush=True)
    container='rezak-vod-'+video_id+'-'+uuid.uuid4().hex[:8]
    command=[*prefix,'--name',container,'recorder','--stream-segment-threads','4','--stream-segment-attempts','3',
             '--stream-segment-timeout','30','--stream-timeout','60','--progress','force','--output',
             f'/recordings/vod_{video_id}/recording.part.ts',url,quality]
    log=directory/'download.log';process=None
    try:
        with log.open('w',encoding='utf-8') as stream:
            process=subprocess.Popen(command,cwd=root,stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
            last_report=0
            while process.poll() is None:
                now=time.time()
                if shutil.disk_usage(directory).free<1024**3:raise RuntimeError('Download stopped: less than 1 GiB free disk space')
                if now-metadata['started']>24*3600:raise RuntimeError('Download exceeded 24 hours')
                if now-last_report>=15:
                    size=partial.stat().st_size if partial.exists() else 0
                    print(f'Downloaded {size/1024**2:.1f} MiB | elapsed {now-metadata["started"]:.0f}s',flush=True);last_report=now
                time.sleep(1)
            if process.returncode:raise RuntimeError('Streamlink failed; inspect '+str(log))
        if not partial.exists() or partial.stat().st_size<1024:raise RuntimeError('No usable recording was downloaded')
        check=subprocess.run(['docker','compose','run','--rm','-T','--entrypoint','ffprobe','-v',str(directory)+':/input:ro','app',
                              '-v','error','-show_format','-show_streams','-of','json','/input/recording.part.ts'],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=120)
        if check.returncode:raise RuntimeError('Downloaded file failed media probe; partial retained')
        probe=json.loads(check.stdout)
        if not all(any(s.get('codec_type')==kind for s in probe.get('streams',[])) for kind in ('video','audio')):raise RuntimeError('Downloaded file lacks audio or video')
        duration=float(probe['format']['duration'])
        if duration<=0:raise RuntimeError('Invalid recording duration')
        warnings=[line[-500:] for line in log.read_text(encoding='utf-8',errors='replace').splitlines() if '[warning]' in line.lower() or '[error]' in line.lower()]
        partial.replace(target)
        metadata.update(status='ready_with_warnings' if warnings else 'ready',finished=time.time(),bytes=target.stat().st_size,duration_ms=round(duration*1000),warnings=warnings[-30:])
        metadata_file.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        (directory/'recording.probe.json').write_text(json.dumps(probe,indent=2),encoding='utf-8')
        print(json.dumps({'file':str(target),'bytes':target.stat().st_size,'duration_seconds':duration,'warnings':warnings[-5:]},ensure_ascii=True),flush=True)
        return target
    except BaseException as exc:
        if process is not None and process.poll() is None:
            subprocess.run(['docker','stop','--time','5',container],cwd=root,capture_output=True,timeout=30)
            process.terminate()
        metadata.update(status='failed',error=str(exc),finished=time.time())
        metadata_file.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        raise

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('url');parser.add_argument('--quality',default='best');args=parser.parse_args()
    try:download(args.url,args.quality)
    except (ValueError,RuntimeError,OSError,subprocess.TimeoutExpired) as exc:parser.exit(1,str(exc)+'\n')
