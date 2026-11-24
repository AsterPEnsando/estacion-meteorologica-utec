"""Receptor HC-05. Solo las tramas válidas actualizan la conexión y el almacenamiento."""
import logging
import math
import random
import threading
import time
from datetime import datetime
import serial
from sensor_protocol import SensorProtocol, light_fields

PSOC_READY = 'PSOC5LP_READY'
PSOC_ADC_MAX = 4095
AVR_CYCLE = {'R', 'L', 'A', 'B', 'C'}


def parse_frame(line):
    """Trama CSV del PSoC 5LP: T_AHT20,T_BMP280,HUM,PRES,LDR_ADC,ESTADO_LLUVIA.

    `nan` (sensor digital con fallo) se convierte en None. El estado de lluvia es
    0 SECO, 1 MODERADO, 2 INTENSO. El mensaje de arranque PSOC5LP_READY no es dato.
    """
    if line.strip().upper() == PSOC_READY:
        return None
    parts = line.strip().split(',')
    if len(parts) != 6:
        raise ValueError('Se esperaban seis campos CSV (PSoC)')
    names = ('AHT20', 'BMP280', 'humedad', 'presion', 'LDR', 'lluvia')
    limits = [(-40, 85), (-40, 85), (0, 100), (300, 1100), (0, PSOC_ADC_MAX), (0, 2)]
    values = []
    for i, (part, (low, high)) in enumerate(zip(parts, limits)):
        part = part.strip()
        if part.upper() in ('', 'NA', 'NAN', 'NULL'):
            if i >= 4:
                raise ValueError(f'{names[i]} es obligatorio en la trama PSoC')
            values.append(None)
            continue
        value = float(part)
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{names[i]} fuera de rango: {part}')
        if i >= 4 and not value.is_integer():
            raise ValueError(f'{names[i]} debe ser entero: {part}')
        values.append(value)
    aht, bmp, hum, pres, light, level = values
    light, level = int(light), int(level)
    return dict(temp_ds=None, temp_aht=aht, temp_bmp=bmp,
                temp_avg=(aht + bmp) / 2 if aht is not None and bmp is not None else None,
                humidity=hum, pressure=pres, light=light, rain=int(level > 0),
                rain_level=level, rain_adc=None, platform='psoc5lp',
                **light_fields(light, PSOC_ADC_MAX))


class Receiver:
    def __init__(self, settings, real_db, demo_db, sync=None):
        self.lock = threading.RLock()
        self.settings = settings.copy()
        self.dbs = {False: real_db, True: demo_db}
        self.sync = sync  # FirebaseSync opcional; solo recibe registros reales almacenados
        self.latest = None
        self.received = None
        self.last_save = None
        self.state = 'disconnected'
        self.error = None
        self.storage_error = None
        self.invalid_frames = 0
        self.protocol = SensorProtocol()
        self.hex_mode = False
        self.cycle = None
        self.stop_event = threading.Event()
        self.changed = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def configure(self, settings):
        with self.lock:
            self.settings = settings.copy()
            self.latest = self.received = self.last_save = None
            self.protocol = SensorProtocol()
            self.hex_mode = False
            self.cycle = None
            self.state = 'connecting'
            self.error = None
            self.changed.set()

    def accept(self, reading, store=True):
        """Publica la lectura en la interfaz; solo se almacena si `store` y vence el intervalo."""
        with self.lock:
            now = time.monotonic()
            reading = {**reading, 'timestamp': datetime.now().astimezone().isoformat(timespec='milliseconds')}
            self.latest = reading
            self.received = now
            self.state = 'connected'
            self.error = None
            if store and (self.last_save is None or now-self.last_save >= self.settings['storage_interval']):
                try:
                    self.dbs[self.settings['demo']].insert(reading)
                    self.last_save = now
                    self.storage_error = None
                    if self.sync is not None and not self.settings['demo']:
                        self.sync.publish_history(reading)
                except Exception as exc:
                    self.storage_error = str(exc)
                    logging.exception('Error de almacenamiento')

    def snapshot(self):
        with self.lock:
            if self.hex_mode and self.latest:
                self.latest = {**self.latest, **self.protocol.snapshot(self.settings['stale_seconds'])}
            age = time.monotonic()-self.received if self.received is not None else None
            state = self.state
            if state == 'connected' and age > self.settings['stale_seconds']:
                state = 'stale'
            cloud = self.sync.info() if self.sync is not None else dict(status='desactivado', error=None, pending=0, sent=0)
            return dict(latest=self.latest, age=age, state=state, error=self.error, sensor_errors=self.protocol.errors.copy(), storage_error=self.storage_error, invalid_frames=self.invalid_frames, settings=self.settings.copy(), cloud=cloud)

    def process_line(self, line):
        with self.lock:
            if not line:
                return
            if '=' not in line:
                self.hex_mode = False
                self.cycle = None
                reading = parse_frame(line)
                if reading is not None:
                    self.accept(reading)
                return
            # ATmega328P: cinco líneas por ciclo (R, L, A, B, C). R reinicia el ensamblado;
            # el ciclo se almacena solo al llegar C con las cinco líneas presentes.
            self.hex_mode = True
            kind = line.split('=', 1)[0].strip().upper()
            stale = self.settings['stale_seconds']
            if kind == 'R':
                self.cycle = set()
            error = None
            try:
                self.protocol.feed(line, stale)
            except ValueError as exc:
                error = exc
            if self.cycle is not None and kind in AVR_CYCLE:
                self.cycle.add(kind)
            snap = self.protocol.snapshot(stale)
            complete = kind == 'C' and self.cycle == AVR_CYCLE
            if complete:
                self.cycle = None
            if complete or error is None:
                self.accept(snap, store=complete)
            elif self.latest:
                self.latest = {**self.latest, **snap}
            if error is not None:
                raise error

    def run(self):
        while not self.stop_event.is_set():
            self.changed.clear()
            with self.lock:
                cfg = self.settings.copy()
                self.state = 'connecting'
            if cfg['demo']:
                while not self.changed.is_set() and not self.stop_event.is_set():
                    t = time.time()/120
                    demo = parse_frame(f'{24+math.sin(t):.2f},{24.4+math.sin(t):.2f},{65+5*math.sin(t/2):.2f},{1012+2*math.sin(t/3):.2f},{int(2600+400*math.sin(t))},{random.choices((0,1,2),(92,6,2))[0]}')
                    self.accept({**demo, 'platform': 'demo'})
                    self.changed.wait(1)
                continue
            try:
                with serial.Serial(cfg['port'], cfg['baudrate'], timeout=1, bytesize=8, parity='N', stopbits=1) as port:
                    with self.lock:
                        self.state = 'stale'
                        self.protocol = SensorProtocol()
                        self.cycle = None
                    buffer = b''
                    last_bytes = time.monotonic()
                    # En Windows, el COM de Bluetooth SPP sigue "abierto" aunque el HC-05 se apague o
                    # se cambie de plataforma; sin error no habría reconexión. Si no llega ningún byte
                    # en este tiempo, se cierra y se vuelve a abrir el puerto.
                    silence = max(10, 2 * cfg['stale_seconds'])
                    while not self.changed.is_set() and not self.stop_event.is_set():
                        chunk = port.read_until(b'\n', 256)
                        if not chunk:
                            if time.monotonic() - last_bytes > silence:
                                raise TimeoutError(f'Sin datos durante {silence} s; reabriendo puerto')
                            continue
                        last_bytes = time.monotonic()
                        buffer += chunk
                        if len(buffer) > 1024:
                            buffer = b''
                            raise ValueError('Trama demasiado larga o sin salto de línea')
                        if not buffer.endswith(b'\n'):
                            continue
                        raw, buffer = buffer, b''
                        try:
                            self.process_line(raw.decode('utf-8').strip())
                        except (ValueError, UnicodeError) as exc:
                            with self.lock:
                                self.invalid_frames += 1
                                self.error = str(exc)
                            logging.warning('Trama descartada: %s', exc)
            except Exception as exc:
                with self.lock:
                    self.state = 'disconnected'
                    self.error = str(exc)
                logging.warning('Serial: %s', exc)
                self.changed.wait(3)
