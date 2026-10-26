"""Bounded process capture, without shell execution."""
import subprocess
import threading
import time

class ProcessError(RuntimeError):
    pass

def run(args, timeout=300, cancel=None, cwd=None, on_stdout=None):
    process = subprocess.Popen([str(a) for a in args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, shell=False)
    buffers = [bytearray(), bytearray()]
    def drain(pipe, target, limit, callback=None):
        with pipe:
            while chunk := pipe.readline(4096):
                target.extend(chunk)
                if len(target) > limit:
                    del target[:-limit]
                if callback:
                    try:
                        callback(chunk.decode('utf-8', errors='replace').strip())
                    except Exception:
                        pass  # A progress observer must never block pipe draining.
    readers = [threading.Thread(target=drain,args=(process.stdout,buffers[0],4*1024*1024,on_stdout)),threading.Thread(target=drain,args=(process.stderr,buffers[1],8192))]
    for reader in readers: reader.start()
    deadline = time.monotonic()+timeout
    try:
        while process.poll() is None:
            if cancel is not None and cancel.is_set():
                raise ProcessError('operation cancelled')
            if time.monotonic()>deadline:
                raise ProcessError('process timeout')
            time.sleep(.05)
    except BaseException:
        process.kill()
        process.wait()
        raise
    finally:
        for reader in readers: reader.join()
    if process.returncode:
        raise ProcessError(f"exit {process.returncode}: {buffers[1].decode('utf-8',errors='replace')}")
    return buffers[0].decode('utf-8',errors='replace')
