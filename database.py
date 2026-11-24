import sqlite3
from contextlib import contextmanager
from config import DATA

FIELDS = ('temp_ds', 'temp_bmp', 'temp_avg', 'humidity', 'pressure', 'light', 'rain', 'temp_aht', 'rain_level', 'rain_adc', 'platform', 'adc_max', 'light_pct')

class Database:
    def __init__(self, path=None):
        self.path = path or DATA / 'meteorologia.db'
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS measurements (id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL UNIQUE, temp_ds REAL, temp_bmp REAL, temp_avg REAL, humidity REAL, pressure REAL, light INTEGER, rain INTEGER)')
            db.execute('CREATE INDEX IF NOT EXISTS idx_time ON measurements(timestamp)')
            columns = {r[1] for r in db.execute('PRAGMA table_info(measurements)')}
            for name, kind in [('temp_aht','REAL'),('rain_level','INTEGER'),('rain_adc','INTEGER'),('platform','TEXT'),('adc_max','INTEGER'),('light_pct','REAL')]:
                if name not in columns:
                    db.execute(f'ALTER TABLE measurements ADD COLUMN {name} {kind}')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def insert(self, reading):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO measurements (timestamp,' + ','.join(FIELDS) + ') VALUES (' + ','.join('?' for _ in range(len(FIELDS)+1)) + ')', [reading['timestamp']] + [reading.get(k) for k in FIELDS])

    def query(self, start, end, page=1, size=25, order='desc', all_rows=False):
        direction = 'ASC' if order == 'asc' else 'DESC'
        with self.connect() as db:
            count = db.execute('SELECT COUNT(*) FROM measurements WHERE timestamp >= ? AND timestamp <= ?', (start, end)).fetchone()[0]
            sql = f'SELECT * FROM measurements WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp {direction}'
            args = [start, end]
            if not all_rows:
                sql += ' LIMIT ? OFFSET ?'
                args += [size, (page - 1) * size]
            return [dict(r) for r in db.execute(sql, args)], count

    def stats(self):
        with self.connect() as db:
            row = db.execute('SELECT COUNT(*), MAX(timestamp) FROM measurements').fetchone()
            return dict(count=row[0], last_stored=row[1])
