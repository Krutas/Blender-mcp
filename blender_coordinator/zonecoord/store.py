"""Durable job state. Geometry acceptance is not visual approval."""
import json
import sqlite3
import time
import uuid
from pathlib import Path
from .core import digest, validate_config


class Store:
    def __init__(self,path,config):
        tasks=validate_config(config)
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=DELETE;
        PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,ordinal INTEGER UNIQUE,
          task TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER DEFAULT 0,
          error TEXT,receipt TEXT,updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, task_id TEXT,
          status TEXT,detail TEXT,at REAL);
        ''')
        # Endpoint/inference settings are also frozen to make resumed experiments auditable.
        signature=digest(config)
        previous=self.db.execute("SELECT value FROM metadata WHERE key='configuration'").fetchone()
        if previous and previous[0]!=signature:
            self.db.close();raise ValueError('configuration changed; use a new --state directory')
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES('configuration',?)",(signature,))
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES('job_id',?)",(uuid.uuid4().hex,))
            for i,t in enumerate(tasks):
                self.db.execute('INSERT OR IGNORE INTO tasks(id,ordinal,task,updated) VALUES(?,?,?,?)',
                                (t['id'],i,json.dumps(t),time.time()))
        self.job_id=self.db.execute("SELECT value FROM metadata WHERE key='job_id'").fetchone()[0]

    def close(self): self.db.close()

    def rows(self): return [dict(r) for r in self.db.execute('SELECT * FROM tasks ORDER BY ordinal')]

    def get(self,task_id):
        row=self.db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
        if row is None: raise ValueError('unknown task: '+task_id)
        return dict(row)

    def counts(self):
        return {r[0]:r[1] for r in self.db.execute('SELECT status,count(*) FROM tasks GROUP BY status')}

    def state(self,task_id,status,detail=None,receipt=None,attempt=False):
        if status not in {'pending','running','uncertain','failed','needs_review','reviewed','rejected'}:
            raise ValueError('invalid status')
        self.get(task_id)
        with self.db:
            self.db.execute('''UPDATE tasks SET status=?,error=?,receipt=COALESCE(?,receipt),
              attempts=attempts+?,updated=? WHERE id=?''',
              (status,detail,json.dumps(receipt) if receipt else None,int(attempt),time.time(),task_id))
            self.db.execute('INSERT INTO events(task_id,status,detail,at) VALUES(?,?,?,?)',
                            (task_id,status,detail,time.time()))

    def token(self,task_id): return digest([self.job_id,task_id])[:24]


class JobLock:
    """OS-owned lock: releases on process death, file itself may remain."""
    def __init__(self,path): self.path=Path(path)
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.file=self.path.open('a+b')
        self.file.seek(0);self.file.write(b'0');self.file.flush();self.file.seek(0)
        try:
            import os
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();raise RuntimeError('another coordinator holds this state directory')
        return self
    def __exit__(self,*args): self.file.close()
