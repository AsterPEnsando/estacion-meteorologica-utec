import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from app import create_app
from bluetooth import parse_frame, Receiver
from database import Database
from config import DEFAULTS

FRAME = '28.96,29.67,75.39,1006.12,2800,0'  # formato PSoC real (valores del contexto)

class ParserTests(unittest.TestCase):
    def test_values_and_missing(self):
        r = parse_frame(FRAME)
        self.assertAlmostEqual(r['temp_avg'],29.315)
        self.assertEqual((r['temp_aht'],r['light'],r['rain_level'],r['platform'],r['adc_max']),(28.96,2800,0,'psoc5lp',4095))
        self.assertIsNone(r['temp_ds'])
        self.assertAlmostEqual(r['light_pct'],68.38,places=2)
        nan = parse_frame('nan,nan,nan,nan,4095,2')
        self.assertIsNone(nan['temp_aht']); self.assertIsNone(nan['pressure']); self.assertIsNone(nan['temp_avg'])
        self.assertEqual((nan['rain'],nan['rain_level'],nan['light_pct']),(1,2,100.0))
        self.assertIsNone(parse_frame('PSOC5LP_READY'))

    def test_invalid(self):
        for value in ['1,2','inf,25,50,1000,500,0','25,25,101,1000,500,0','25,25,50,1000,1.5,0','25,25,50,1000,500,3','25,25,50,1000,4096,0','25,25,50,1000,nan,0','25,25,50,1000,500,nan','basura','25,25,50,1000,500,0,9']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_frame(value)

class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(False,Path(self.tmp.name))
        self.client = self.app.test_client()
        self.receiver = self.app.extensions['receiver']

    def tearDown(self):
        self.tmp.cleanup()

    def test_initial_load_and_assets(self):
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertIsNone(self.client.get('/api/status').json['latest'])
        self.assertFalse(self.client.get('/api/status').json['settings']['demo'])
        for asset in ['/static/js/dashboard.js','/static/css/styles.css','/static/vendor/chart.umd.js']:
            response = self.client.get(asset)
            self.assertEqual(response.status_code,200)
            response.close()

    def test_storage_interval_history_and_export(self):
        with patch('bluetooth.time.monotonic',side_effect=[100,101,160]):
            for _ in range(3):
                self.receiver.accept(parse_frame(FRAME))
        self.assertEqual(self.receiver.dbs[False].stats()['count'],2)
        history=self.client.get('/api/history').json
        self.assertEqual(history['count'],2)
        self.assertEqual(self.client.get('/api/history?chart=1').json['rows'][0]['temp_aht'],28.96)
        self.assertIn('28.96',self.client.get('/api/export').data.decode('utf-8-sig'))
        self.assertEqual(self.client.get('/api/history?start=bad').status_code,400)

    def test_demo_isolation_and_config(self):
        settings={**DEFAULTS,'demo':True}
        with patch('app.config.save'):
            response=self.client.post('/api/settings',json=settings)
        self.assertEqual(response.status_code,200)
        self.receiver.accept(parse_frame(FRAME))
        self.assertEqual(self.receiver.dbs[False].stats()['count'],0)
        self.assertEqual(self.receiver.dbs[True].stats()['count'],1)
        self.assertEqual(self.client.get('/api/history').json['count'],1)
        with patch('app.config.save'):
            self.client.post('/api/settings',json=DEFAULTS)
        self.assertEqual(self.client.get('/api/history').json['count'],0)
        self.assertIsNone(self.receiver.latest)
        self.assertEqual(self.client.post('/api/settings',json={**DEFAULTS,'storage_interval':0}).status_code,400)
        self.assertEqual(self.client.post('/api/settings',json=DEFAULTS,headers={'Origin':'https://example.com'}).status_code,403)

    def test_stale_and_duplicates(self):
        with patch('bluetooth.time.monotonic',return_value=100):
            self.receiver.accept(parse_frame(FRAME))
        with patch('bluetooth.time.monotonic',return_value=116):
            self.assertEqual(self.receiver.snapshot()['state'],'stale')
        reading=self.receiver.latest
        self.receiver.dbs[False].insert(reading)
        self.assertEqual(self.receiver.dbs[False].stats()['count'],1)

    def test_serial_stream(self):
        receiver=self.receiver
        class FakePort:
            def __init__(self,*args,**kwargs):
                self.lines=iter([b'PSOC5LP_READY\r\n',b'broken\n',b'28.96,29.67,75.39,1006.12,2800,0\r\n'])
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read_until(self,*args):
                try: return next(self.lines)
                except StopIteration:
                    receiver.stop_event.set()
                    return b''
        with patch('bluetooth.serial.Serial',FakePort):
            receiver.run()
        self.assertEqual(receiver.invalid_frames,1)
        self.assertEqual(receiver.latest['light'],2800)
        self.assertEqual(receiver.latest['platform'],'psoc5lp')
        self.assertEqual(receiver.dbs[False].stats()['count'],1)

    def test_demo_worker(self):
        self.receiver.configure({**DEFAULTS,'demo':True})
        original=self.receiver.accept
        def accept_and_stop(reading):
            original(reading)
            self.receiver.stop_event.set()
            self.receiver.changed.set()
        with patch.object(self.receiver,'accept',side_effect=accept_and_stop):
            self.receiver.run()
        self.assertEqual(self.receiver.dbs[True].stats()['count'],1)
        self.assertEqual(self.receiver.dbs[False].stats()['count'],0)

if __name__ == '__main__':
    unittest.main()
