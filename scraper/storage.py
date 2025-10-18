
import os
import sqlite3
from datetime import datetime
from typing import Dict

class Storage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._create()

    def _create(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                company TEXT,
                location TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def seen(self, job_id: str) -> bool:
        cur = self._conn.execute('SELECT 1 FROM jobs WHERE job_id = ?', (job_id,))
        return cur.fetchone() is not None

    def upsert(self, job: Dict):
        now = datetime.utcnow().isoformat()
        if self.seen(job['job_id']):
            self._conn.execute('UPDATE jobs SET last_seen = ? WHERE job_id = ?', (now, job['job_id']))
        else:
            self._conn.execute(
                'INSERT INTO jobs(job_id, url, title, company, location, first_seen, last_seen) VALUES(?,?,?,?,?,?,?)',
                (
                    job['job_id'], job['url'], job['title'], job.get('company'), job.get('location'), now, now
                )
            )
        self._conn.commit()

    def close(self):
        self._conn.close()
