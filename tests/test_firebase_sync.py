import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from firebase_sync import FirebaseSync, load_env, public
from bluetooth import parse_frame, Receiver
from database import Database
from config import DEFAULTS

ENV = dict(FIREBASE_DB_URL='https://demo-rtdb.example', FIREBASE_API_KEY='k', FIREBASE_EMAIL='c@x.test', FIREBASE_PASSWORD='p', FIREBASE_LIVE_SECONDS='1')


class FakeHTTP:
    """Simula Firebase Auth + RTDB REST. `fail` hace fallar las escrituras a la base."""
    def __init__(self):
        self.calls, self.db, self.fail = [], {}, False

    def __call__(self, req, timeout=None):
        body = json.loads(req.data) if req.data else None
        self.calls.append((req.get_method(), req.full_url, body))
        if 'identitytoolkit' in req.full_url:
            out = {'idToken': 'tok', 'refreshToken': 'ref', 'expiresIn': '3600'}
        else:
            if self.fail:
                raise urllib.error.URLError('sin internet')
            path = req.full_url.split('.example/')[1].split('.json')[0]
            if req.get_method() == 'PATCH':
                self.db.setdefault(path, {}).update(body)
            else:
                self.db[path] = body
            out = body
        return io.BytesIO(json.dumps(out).encode())


class SyncTests(unittest.TestCase):
    def test_disabled_without_env(self):
        self.assertFalse(FirebaseSync(env={}).enabled)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / '.env'
            p.write_text('# c\nFIREBASE_DB_URL="https://x"\nFIREBASE_ROOT=est\n', 'utf-8')
            self.assertEqual(load_env(p), {'FIREBASE_DB_URL': 'https://x', 'FIREBASE_ROOT': 'est'})

    def test_public_fields_only(self):
        r = {**parse_frame('28.96,nan,75.39,1006.12,2800,1'), 'timestamp': '2026-11-24T13:00:00.000-05:00'}
        row = public(r)
        self.assertEqual(row['ts'], 1795543200000)
        self.assertNotIn('temp_bmp', row)  # nan -> ausente, no 0
        self.assertNotIn('temp_ds', row)
        self.assertEqual((row['platform'], row['rain_level'], row['adc_max']), ('psoc5lp', 1, 4095))

    def test_history_idempotent_and_retry(self):
        http = FakeHTTP()
        s = FirebaseSync(env=ENV, opener=http)
        r = {**parse_frame('28.96,29.67,75.39,1006.12,2800,0'), 'timestamp': '2026-11-24T13:00:00.000-05:00'}
        http.fail = True
        s.publish_history(r)
        with self.assertRaises(urllib.error.URLError):
            s.step()
        self.assertEqual(s.info()['pending'], 1)  # se conserva en cola
        http.fail = False
        s.publish_history(r)  # mismo registro reenviado: misma clave
        self.assertTrue(s.step())
        self.assertEqual(list(http.db['estacion/history']), ['1795543200000'])
        self.assertTrue(all('auth=tok' in url for m, url, _ in http.calls if 'rtdb' in url))
        self.assertEqual(sum('identitytoolkit' in c[1] for c in http.calls), 1)  # token reutilizado

    def test_live_excludes_demo(self):
        http = FakeHTTP()
        s = FirebaseSync(env=ENV, opener=http)
        demo = {**parse_frame('24,24,60,1010,2000,0'), 'platform': 'demo', 'timestamp': '2026-11-24T13:00:00.000-05:00'}
        s.publish_live({'state': 'connected', 'latest': demo, 'demo': True})
        s.step()
        live = http.db['estacion/live']
        self.assertIsNone(live['latest'])
        self.assertTrue(live['demo'])
        self.assertEqual(live['heartbeat'], {'.sv': 'timestamp'})
        s.publish_history(demo)
        self.assertEqual(s.info()['pending'], 0)

    def test_receiver_sends_only_stored_real_rows(self):
        http = FakeHTTP()
        s = FirebaseSync(env=ENV, opener=http)
        with tempfile.TemporaryDirectory() as d:
            rx = Receiver({**DEFAULTS, 'storage_interval': 60}, Database(Path(d) / 'r.db'), Database(Path(d) / 'd.db'), s)
            rx.accept(parse_frame('28.96,29.67,75.39,1006.12,2800,0'))
            rx.accept(parse_frame('28.97,29.67,75.39,1006.12,2800,0'))  # dentro del intervalo: no se guarda ni se envía
            self.assertEqual(s.info()['pending'], 1)
            self.assertEqual(rx.snapshot()['cloud']['pending'], 1)


if __name__ == '__main__':
    unittest.main()
