import json
import threading
import time
from pathlib import Path

import pytest

from rezak.jobs import JobRunner
from rezak.store import Store


def test_metadata_merge_does_not_clobber_concurrent_writers(tmp_path):
    """Two writers touching the same job must not lose each other's keys."""
    store = Store(tmp_path / 'app')
    job = store.create_job('MOCK', 'source')
    store.patch_job_metadata(job['id'], chunks=[{'file': 'part-0.ts'}])
    store.patch_job_metadata(job['id'], bytes=1234)
    metadata = store.job(job['id'])['metadata']
    assert metadata['chunks'] == [{'file': 'part-0.ts'}]
    assert metadata['bytes'] == 1234


def test_metadata_merge_under_parallel_writers_keeps_every_key(tmp_path):
    store = Store(tmp_path / 'app')
    job = store.create_job('MOCK', 'source')
    def writer(index):
        for _ in range(20):
            store.patch_job_metadata(job['id'], **{f'key{index}': index})
    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    metadata = store.job(job['id'])['metadata']
    for index in range(4):
        assert metadata[f'key{index}'] == index


def test_cancelled_process_does_not_leak_the_reader_thread(tmp_path):
    """Cancelling a job must not leave a reader thread blocked on a full queue.

    The reader used to put lines into a bounded queue without a timeout. Once the
    job was cancelled the consumer stopped reading, the queue filled up and the
    reader blocked forever while the pipe was closed underneath it.
    """
    runner = JobRunner(Store(tmp_path / 'app'), tmp_path)
    cancel = threading.Event()
    script = ('import sys\n'
              'out=sys.stdout\n'
              'for i in range(200000):\n'
              '    out.write("line %d padding padding padding\\n" % i)\n'
              'out.flush()\n'
              'import time; time.sleep(30)\n')
    failures = []
    original_hook = threading.excepthook

    def hook(args):
        failures.append(args.exc_type.__name__)

    threading.excepthook = hook
    timer = threading.Timer(.5, cancel.set)
    timer.start()
    before = {t.ident for t in threading.enumerate()}
    try:
        with pytest.raises(Exception):
            runner.execute(['python', '-c', script], 'job', cancel, timeout=30)
    finally:
        timer.cancel()
        threading.excepthook = original_hook
    time.sleep(.6)
    leaked = [t for t in threading.enumerate() if t.ident not in before and t.name.startswith('Thread')]
    assert not failures, failures
    assert not leaked, [t.name for t in leaked]


def test_owner_is_resolved_from_metadata_or_parent_recording(tmp_path):
    runner = JobRunner(Store(tmp_path / 'app'), tmp_path)
    store = runner.store
    streamer = store.add_streamer('alpha')
    capture = store.create_job('LIVE', 'capture', kind='capture',
                               metadata={'streamer_id': streamer['id']})
    child = store.create_job('part', 'part', metadata={'recording_job': capture['id']})
    assert runner.resolve_owner(child) == streamer['id']
    direct = store.create_job('part', 'part2', metadata={'streamer_id': streamer['id']})
    assert runner.resolve_owner(direct) == streamer['id']
    orphan = store.create_job('part', 'part3', metadata={})
    assert runner.resolve_owner(orphan) is None


def test_preparation_removes_the_temp_file_when_ffmpeg_fails(tmp_path, monkeypatch):
    store = Store(tmp_path / 'app')
    runner = JobRunner(store, tmp_path)
    source = tmp_path / 'data' / 'imports' / 'clip.mp4'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b'x' * 32)
    job = store.create_job('MOCK', 'clip', input_path=source)

    def failing_execute(args, job_id, cancel, **kwargs):
        target = [a for a in args if str(a).endswith('.preparing.mp4')]
        assert target, args
        Path(target[0]).write_bytes(b'partial')
        raise RuntimeError('ffmpeg failed')

    monkeypatch.setattr(runner, 'execute', failing_execute)
    monkeypatch.setattr('rezak.jobs.probe', lambda path: {
        'streams': [{'codec_type': 'video'}, {'codec_type': 'audio'}],
        'format': {'duration': '1.0'},
    })
    with pytest.raises(RuntimeError):
        runner.prepare(job, threading.Event())
    assert not list((tmp_path / 'data' / 'sources').glob('*.preparing.mp4'))
