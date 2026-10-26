"""Single Streamlink connection piped into FFmpeg's closed-segment playlist."""
import argparse
from pathlib import Path
import subprocess
import sys
import signal

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('directory');parser.add_argument('login');parser.add_argument('quality')
    args=parser.parse_args();directory=Path(args.directory);directory.mkdir(parents=True,exist_ok=True)
    stream=subprocess.Popen([sys.executable,'-m','streamlink','--retry-streams','10','--retry-max','3',
        '--stream-segment-attempts','3','--stream-timeout','60','--stdout','https://www.twitch.tv/'+args.login,args.quality],stdout=subprocess.PIPE)
    stopping=False
    def stop(signum,frame):
        nonlocal stopping
        stopping=True
        if stream.poll() is None:stream.terminate()
    signal.signal(signal.SIGTERM,stop)
    try:
        result=subprocess.run(['ffmpeg','-v','warning','-nostdin','-i','pipe:0','-map','0:v:0','-map','0:a:0','-c','copy',
            '-f','segment','-segment_time','120','-reset_timestamps','1','-segment_list',str(directory/'closed.csv'),
            '-segment_list_type','csv',str(directory/'live-%06d.ts')],stdin=stream.stdout)
        stream.stdout.close()
        if result.returncode:raise RuntimeError('Live segment muxer failed: '+str(result.returncode))
        code=stream.wait(timeout=30)
        if code and not stopping:raise RuntimeError('Streamlink disconnected: '+str(code))
    finally:
        if stream.poll() is None:stream.terminate();stream.wait(timeout=15)

if __name__=='__main__':main()
