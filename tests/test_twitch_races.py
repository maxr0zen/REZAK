import threading
import time
from types import SimpleNamespace

from rezak.store import Store
from rezak.twitch import TwitchMonitor


def test_wake_up_shortens_the_poll_wait(tmp_path, monkeypatch):
    """After a wake-up the monitor must poll again without waiting a full interval."""
    store = Store(tmp_path)
    monitor = TwitchMonitor(store, SimpleNamespace())
    store.add_streamer('alpha')
    polls = []

    def poll():
        polls.append(time.monotonic())
        if len(polls) == 1:
            # A handler asks for an immediate re-check.
            monitor.wake.set()

    monkeypatch.setattr(monitor, 'poll', poll)
    monkeypatch.setattr(store, 'setting', lambda key, default=None: 300 if key == 'poll_interval' else default)
    monitor.thread = threading.Thread(target=monitor.loop, name='twitch-test', daemon=True)
    monitor.thread.start()
    deadline = time.monotonic() + 5
    while len(polls) < 2 and time.monotonic() < deadline:
        time.sleep(.05)
    monitor.stopping.set()
    monitor.wake.set()
    monitor.thread.join(timeout=5)
    assert len(polls) >= 2, polls
    # The second poll must follow immediately, not after the 300 s interval.
    assert polls[1] - polls[0] < 5, polls


def test_record_does_not_create_two_recordings_for_one_stream(tmp_path, monkeypatch):
    """The monitor thread and the HTTP handler must not both start a recording."""
    store = Store(tmp_path)
    monitor = TwitchMonitor(store, SimpleNamespace())
    streamer = store.add_streamer('alpha')
    monkeypatch.setattr(monitor, 'capture', lambda *a: None)
    live = {**store.streamers()[0], 'status': 'live', 'stream_id': 'stream-1',
            'title': 'Live now', 'display_name': 'alpha'}
    original_create = store.create_job

    def slow_create(*args, **kwargs):
        # Widen the window between the "is a recording active?" check and the
        # insert, which is where two concurrent callers could both pass.
        time.sleep(.3)
        return original_create(*args, **kwargs)

    monkeypatch.setattr(store, 'create_job', slow_create)
    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(monitor.record(live))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    recordings = [j for j in store.jobs() if j['kind'] == 'capture']
    assert len(recordings) == 1, [r['id'] for r in recordings]
    assert results[0]['id'] == results[1]['id']


def test_recording_progress_does_not_drop_the_chunk_list(tmp_path):
    """The size watcher updates bytes while the capture thread owns the chunk list."""
    store = Store(tmp_path)
    job = store.create_job('LIVE', 'capture', kind='capture', metadata={'streamer_id': 'x'})
    store.patch_job_metadata(job['id'], chunks=[{'file': 'part-0000.ts', 'bytes': 10}])
    store.patch_job_metadata(job['id'], bytes=999)
    metadata = store.job(job['id'])['metadata']
    assert metadata['chunks'] == [{'file': 'part-0000.ts', 'bytes': 10}]
    assert metadata['bytes'] == 999
