import struct
import unittest
from unittest.mock import patch
from sensor_protocol import SensorProtocol
import test_app


class ProtocolTests(unittest.TestCase):
    def test_independent_readings_and_errors(self):
        p = SensorProtocol()
        self.assertEqual(p.feed('R=0202FF',15)['rain'],1)
        r = p.feed('L=02DF',15)
        self.assertEqual(r['light'],735)
        self.assertEqual(r['rain_level'],2)
        self.assertEqual(r['rain_adc'],767)
        for kind in 'ABC':
            with self.assertRaises(ValueError): p.feed(kind+'=ERR',15)
        r = p.feed('L=0200',15)
        self.assertEqual(r['light'],512)
        self.assertEqual(r['rain'],1)
        self.assertIsNone(r['temp_bmp'])
        self.assertIsNone(r['temp_avg'])

    def test_aht_and_bmp_reference(self):
        p = SensorProtocol()
        r = p.feed('A=088000060000',15)
        self.assertEqual(r['temp_aht'],25)
        self.assertEqual(r['humidity'],50)
        self.assertIsNone(r['temp_ds'])
        cal = struct.pack('<HhhH'+'h'*8,27504,26435,-1000,36477,-10685,3024,2855,140,-7,15500,-14600,6000)
        self.assertIsNone(p.feed('C='+cal.hex(),15))
        def raw20(n): return (n<<4).to_bytes(3,'big')
        r = p.feed('B='+(raw20(415148)+raw20(519888)).hex(),15)
        self.assertAlmostEqual(r['temp_bmp'],25.08,places=2)
        self.assertAlmostEqual(r['pressure'],1006.53,places=2)
        self.assertAlmostEqual(r['temp_avg'],25.0412,places=3)
        with self.assertRaises(ValueError): p.feed('A=ERR',15)
        self.assertIsNone(p.snapshot(15)['temp_aht'])
        self.assertIsNotNone(p.snapshot(15)['temp_bmp'])
        with self.assertRaises(ValueError): p.feed('C=ERR',15)
        self.assertIsNone(p.snapshot(15)['pressure'])

    def test_expiry_and_invalid_hex(self):
        p = SensorProtocol()
        with patch('sensor_protocol.time.monotonic',return_value=100):
            p.feed('L=02DF',15)
        with patch('sensor_protocol.time.monotonic',return_value=116):
            self.assertIsNone(p.snapshot(15)['light'])
        for frame in ['R=030001','L=FFFF','A=000000000000','B=000000000000','C=00','L=zzzz']:
            with self.subTest(frame=frame), self.assertRaises(ValueError): p.feed(frame,15)


CAL = struct.pack('<HhhH'+'h'*8,27504,26435,-1000,36477,-10685,3024,2855,140,-7,15500,-14600,6000).hex()
B_OK = ((415148<<4).to_bytes(3,'big')+(519888<<4).to_bytes(3,'big')).hex()


class ReceiverProtocolTests(unittest.TestCase):
    setUp = test_app.AppTests.setUp
    tearDown = test_app.AppTests.tearDown

    def cycle(self, lines):
        for line in lines:
            try: self.receiver.process_line(line)
            except ValueError: pass

    def test_partial_cycle_and_ui_status(self):
        self.cycle(['R=010200','L=02DF','A=ERR','B=ERR','C=ERR'])
        status=self.client.get('/api/status').json
        self.assertEqual(status['latest']['light'],735)
        self.assertEqual(status['latest']['rain_level'],1)
        self.assertEqual(status['latest']['platform'],'atmega328p')
        self.assertAlmostEqual(status['latest']['light_pct'],71.85,places=2)
        self.assertIn('A',status['sensor_errors'])
        rows=self.client.get('/api/history').json['rows']
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['light'],rows[0]['platform'],rows[0]['adc_max']),(735,'atmega328p',1023))
        self.assertIsNone(rows[0]['temp_aht'])

    def test_store_only_complete_cycles(self):
        self.cycle(['L=02DF','A=088000060000','B='+B_OK,'C='+CAL])  # ciclo sin R: no se almacena
        self.assertEqual(self.receiver.dbs[False].stats()['count'],0)
        self.assertEqual(self.receiver.latest['light'],735)  # pero la interfaz se actualiza
        self.cycle(['R=0003FF','L=036B','A=088000060000','B='+B_OK,'C='+CAL])
        row=self.client.get('/api/history').json['rows'][0]
        self.assertEqual((row['rain_level'],row['rain_adc'],row['light']),(0,1023,875))
        self.assertAlmostEqual(row['pressure'],1006.53,places=2)
        self.assertAlmostEqual(row['temp_aht'],25.0)

    def test_switch_platform_stream(self):
        self.cycle(['R=0003FF','L=036B','A=ERR','B=ERR','C=ERR'])
        self.receiver.process_line('PSOC5LP_READY')
        self.receiver.process_line('28.96,29.67,75.39,1006.12,2800,0')
        self.assertEqual(self.receiver.latest['platform'],'psoc5lp')
        self.assertEqual(self.receiver.invalid_frames,0)
