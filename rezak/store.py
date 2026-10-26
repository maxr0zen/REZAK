"""Local application state. Short WAL transactions, serialized writes."""
import json
from contextlib import contextmanager
import sqlite3
import threading
import time
import uuid
from pathlib import Path

STAGES = [('prepare', 'Подготовка', 8), ('asr', 'Распознавание', 35),
          ('llm', 'Отбор моментов', 27), ('render', 'Монтаж', 25), ('verify', 'Проверка', 5)]


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'studio.sqlite3'
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, source_id TEXT NOT NULL,
                    kind TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0, stages TEXT NOT NULL DEFAULT '{}',
                    detail TEXT NOT NULL DEFAULT '', profile TEXT NOT NULL DEFAULT 'both',
                    input_path TEXT, created REAL NOT NULL, updated REAL NOT NULL,
                    started REAL, finished REAL, error TEXT, exports TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}', dedupe TEXT UNIQUE);
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, at REAL NOT NULL,
                    level TEXT NOT NULL, message TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS logs_job ON logs(job_id,id);
                CREATE TABLE IF NOT EXISTS streamers (
                    id TEXT PRIMARY KEY, login TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1, auto_record INTEGER NOT NULL DEFAULT 1,
                    auto_clip INTEGER NOT NULL DEFAULT 1, quality TEXT NOT NULL DEFAULT '720p',
                    status TEXT NOT NULL DEFAULT 'waiting', title TEXT NOT NULL DEFAULT '',
                    stream_id TEXT, viewers INTEGER, checked REAL, error TEXT,
                    created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            ''')
            columns={r['name'] for r in db.execute('PRAGMA table_info(streamers)')}
            if 'live_clip' not in columns:db.execute('ALTER TABLE streamers ADD COLUMN live_clip INTEGER NOT NULL DEFAULT 0')
            if 'adhd_mode' not in columns:db.execute('ALTER TABLE streamers ADD COLUMN adhd_mode INTEGER NOT NULL DEFAULT 0')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=10000')
        try:
            with db:
                yield db
        finally:
            db.close()

    def rows(self, query, args=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(query, args)]

    def execute(self, query, args=()):
        with self.lock, self.connect() as db:
            return db.execute(query, args).rowcount

    def setting(self, key, default=None):
        rows = self.rows('SELECT value FROM settings WHERE key=?', (key,))
        return json.loads(rows[0]['value']) if rows else default

    def set_setting(self, key, value):
        self.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     (key, json.dumps(value)))

    def log(self, message, level='info', job_id=None):
        message = str(message).replace('\x00', '')[-4000:]
        with self.lock, self.connect() as db:
            db.execute('INSERT INTO logs(job_id,at,level,message) VALUES (?,?,?,?)',
                       (job_id, time.time(), level, message))
            # Bound persisted UI history per job. Original source media are never removed.
            db.execute('DELETE FROM logs WHERE job_id IS ? AND id NOT IN '
                       '(SELECT id FROM logs WHERE job_id IS ? ORDER BY id DESC LIMIT 2000)', (job_id, job_id))

    def logs(self, job_id=None, after=0, limit=300):
        rows = self.rows('SELECT * FROM logs WHERE job_id IS ? AND id>? ORDER BY id DESC LIMIT ?',
                         (job_id, after, min(limit, 2000)))
        return list(reversed(rows))

    def create_job(self, title, source_id, input_path=None, profile='both', kind='video', metadata=None, dedupe=None):
        job_id = uuid.uuid4().hex
        now = time.time()
        self.execute('INSERT INTO jobs(id,title,source_id,kind,status,stage,input_path,profile,created,updated,metadata,dedupe) '
                     'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                     (job_id, title, source_id, kind, 'queued', 'prepare', str(input_path) if input_path else None,
                      profile, now, now, json.dumps(metadata or {}), dedupe))
        self.log('Задача добавлена в очередь', job_id=job_id)
        return self.job(job_id)

    def decode_job(self, row):
        if row:
            for key in ('stages', 'exports', 'metadata'):
                row[key] = json.loads(row[key])
        return row

    def job(self, job_id):
        rows = self.rows('SELECT * FROM jobs WHERE id=?', (job_id,))
        return self.decode_job(rows[0]) if rows else None

    def jobs(self):
        return [self.decode_job(row) for row in self.rows('SELECT * FROM jobs ORDER BY created DESC LIMIT 200')]

    def update_job(self, job_id, **fields):
        allowed = {'status', 'stage', 'progress', 'stages', 'detail', 'started', 'finished', 'error', 'exports', 'metadata'}
        if not fields or not set(fields) <= allowed:
            raise ValueError('Invalid job update')
        fields['updated'] = time.time()
        for key in ('stages', 'exports', 'metadata'):
            if key in fields:
                fields[key] = json.dumps(fields[key], ensure_ascii=False)
        self.execute('UPDATE jobs SET '+','.join(key+'=?' for key in fields)+' WHERE id=?', (*fields.values(), job_id))

    def event(self, job_id, event):
        job = self.job(job_id)
        if not job or event.get('stage') not in {s[0] for s in STAGES}:
            return
        stage = event['stage']
        stages = job['stages']
        idx = next(i for i, s in enumerate(STAGES) if s[0] == stage)
        for key, _, _ in STAGES[:idx]:
            stages[key] = {**stages.get(key, {}), 'progress': 1, 'status': 'done'}
        previous = stages.get(stage, {})
        value = event.get('progress')
        fraction = max(previous.get('progress', 0), min(1, max(0, float(value)))) if value is not None else previous.get('progress', 0)
        stages[stage] = {**previous, **event, 'progress': fraction,
                         'status': 'done' if fraction == 1 else 'running',
                         'started': previous.get('started', time.time())}
        total = sum(weight*stages.get(key, {}).get('progress', 0) for key, _, weight in STAGES)
        self.update_job(job_id, stage=stage, progress=min(99, max(job['progress'], total)), stages=stages,
                        detail=event.get('message', job['detail']))

    def recover(self):
        rows = self.rows("SELECT id FROM jobs WHERE status IN ('running','recording')")
        for row in rows:
            self.update_job(row['id'], status='interrupted', finished=time.time(),
                            detail='Работа прервана перезапуском. Исходник и артефакты сохранены.')
            self.log('Прерванная задача сохранена; можно запустить повторно', 'warning', row['id'])

    def streamers(self):
        rows = self.rows('SELECT * FROM streamers ORDER BY created')
        for row in rows:
            for key in ('enabled', 'auto_record', 'auto_clip','live_clip','adhd_mode'):
                row[key] = bool(row[key])
        return rows

    def add_streamer(self, login, auto_record=True, auto_clip=True, quality='720p',live_clip=False,adhd_mode=False):
        streamer_id = uuid.uuid4().hex
        self.execute('INSERT INTO streamers(id,login,display_name,auto_record,auto_clip,quality,created) VALUES (?,?,?,?,?,?,?)',
                     (streamer_id, login, login, int(auto_record), int(auto_clip), quality, time.time()))
        self.execute('UPDATE streamers SET live_clip=? WHERE id=?',(int(live_clip),streamer_id))
        self.execute('UPDATE streamers SET adhd_mode=? WHERE id=?',(int(adhd_mode),streamer_id))
        return next(s for s in self.streamers() if s['id'] == streamer_id)

    def update_streamer(self, streamer_id, **fields):
        allowed = {'enabled', 'auto_record', 'auto_clip','live_clip','adhd_mode', 'quality', 'status', 'title', 'stream_id', 'viewers', 'checked', 'error', 'display_name'}
        if not fields or not set(fields) <= allowed:
            raise ValueError('Invalid streamer update')
        self.execute('UPDATE streamers SET '+','.join(key+'=?' for key in fields)+' WHERE id=?', (*fields.values(), streamer_id))
