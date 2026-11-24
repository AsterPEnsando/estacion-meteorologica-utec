"""Sincronización opcional del colector local con Firebase Realtime Database (REST).

- Solo escribe: la laptop conectada al HC-05 es la única fuente de datos.
- Autenticación con un usuario Email/Password de Firebase Auth; las credenciales viven
  en `.env` (ignorado por Git). Las reglas de la base deben exigir ese UID para escribir.
- Estructura bajo FIREBASE_ROOT (por defecto `estacion`):
    live            -> última lectura + estado del colector (se sobrescribe)
    history/<ts_ms> -> registros almacenados en SQLite (clave = epoch ms, idempotente)
- Si Internet cae, el historial pendiente queda en cola (memoria, acotada) y se reintenta
  con espera exponencial. La clave por timestamp evita duplicados al reintentar.
- Los datos del modo demostración nunca se envían.
"""
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KEYS = ('FIREBASE_DB_URL', 'FIREBASE_API_KEY', 'FIREBASE_EMAIL', 'FIREBASE_PASSWORD')
PUBLIC_FIELDS = ('timestamp', 'platform', 'temp_aht', 'temp_bmp', 'temp_avg', 'humidity', 'pressure',
                 'light', 'adc_max', 'light_pct', 'rain', 'rain_level', 'rain_adc')
MAX_QUEUE = 20000


def load_env(path=ROOT / '.env'):
    """Lector mínimo de .env (CLAVE=valor), sin dependencias externas."""
    values = {}
    try:
        for line in Path(path).read_text('utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


def epoch_ms(iso):
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def public(reading):
    """Solo campos de medición; nada de configuración local (puerto, rutas, errores internos)."""
    row = {k: reading.get(k) for k in PUBLIC_FIELDS}
    row['ts'] = epoch_ms(reading['timestamp'])
    return {k: v for k, v in row.items() if v is not None}


class FirebaseSync:
    def __init__(self, env=None, opener=urllib.request.urlopen):
        env = load_env() if env is None else env
        self.enabled = all(env.get(k) for k in KEYS)
        self.db_url = env.get('FIREBASE_DB_URL', '').rstrip('/')
        self.api_key = env.get('FIREBASE_API_KEY', '')
        self.email = env.get('FIREBASE_EMAIL', '')
        self.password = env.get('FIREBASE_PASSWORD', '')
        self.root = env.get('FIREBASE_ROOT', 'estacion').strip('/')
        self.live_interval = max(1.0, float(env.get('FIREBASE_LIVE_SECONDS', 3)))
        self.opener = opener
        self.source = None  # callable que devuelve el estado actual del Receiver
        self.queue = deque(maxlen=MAX_QUEUE)
        self.lock = threading.Lock()
        self.token = self.refresh_token = None
        self.token_expiry = 0
        self.live_pending = None
        self.last_live = 0
        self.status = 'desactivado' if not self.enabled else 'iniciando'
        self.error = None
        self.sent = 0
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    # ---- API usada por el Receiver ----
    def publish_live(self, snapshot):
        if self.enabled:
            with self.lock:
                self.live_pending = snapshot
            self.wake.set()

    def publish_history(self, reading):
        if self.enabled and reading.get('platform') != 'demo':
            with self.lock:
                self.queue.append(public(reading))
            self.wake.set()

    def info(self):
        with self.lock:
            return dict(status=self.status, error=self.error, pending=len(self.queue), sent=self.sent)

    # ---- HTTP ----
    def request(self, method, url, body=None):
        data = None if body is None else json.dumps(body).encode('utf-8')
        req = urllib.request.Request(url, data=data, method=method, headers={'Content-Type': 'application/json'})
        with self.opener(req, timeout=15) as res:
            return json.loads(res.read().decode('utf-8') or 'null')

    def authenticate(self):
        if self.token and time.time() < self.token_expiry - 120:
            return
        key = urllib.parse.quote(self.api_key)
        if self.refresh_token:
            res = self.request('POST', f'https://securetoken.googleapis.com/v1/token?key={key}',
                               {'grant_type': 'refresh_token', 'refresh_token': self.refresh_token})
            self.token, self.refresh_token = res['id_token'], res['refresh_token']
            expires = res['expires_in']
        else:
            res = self.request('POST', f'https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={key}',
                               {'email': self.email, 'password': self.password, 'returnSecureToken': True})
            self.token, self.refresh_token = res['idToken'], res['refreshToken']
            expires = res['expiresIn']
        self.token_expiry = time.time() + int(expires)

    def put(self, path, value):
        self.authenticate()
        url = f'{self.db_url}/{self.root}/{path}.json?auth={urllib.parse.quote(self.token)}'
        self.request('PUT', url, value)

    def patch(self, path, value):
        self.authenticate()
        url = f'{self.db_url}/{self.root}/{path}.json?auth={urllib.parse.quote(self.token)}'
        self.request('PATCH', url, value)

    # ---- Bucle ----
    def step(self):
        """Envía lo pendiente. Devuelve True si no queda nada por enviar."""
        with self.lock:
            live = self.live_pending
            due = live is not None and time.monotonic() - self.last_live >= self.live_interval
        if due:
            latest = live.get('latest')
            body = {'state': live.get('state'), 'platform': (latest or {}).get('platform'),
                    'heartbeat': {'.sv': 'timestamp'},
                    'latest': public(latest) if latest and latest.get('platform') != 'demo' else None,
                    'demo': bool(live.get('demo'))}
            self.put('live', body)
            with self.lock:
                if self.live_pending is live:
                    self.live_pending = None
                self.last_live = time.monotonic()
        batch = []
        with self.lock:
            while self.queue and len(batch) < 200:
                batch.append(self.queue[0])
                self.queue.popleft()
        if batch:
            try:
                self.patch('history', {str(row['ts']): row for row in batch})
            except Exception:
                with self.lock:
                    self.queue.extendleft(reversed(batch))
                raise
            with self.lock:
                self.sent += len(batch)
        with self.lock:
            return not self.queue and self.live_pending is None

    def run(self):
        delay = 2
        while not self.stop_event.is_set():
            self.wake.wait(self.live_interval)
            self.wake.clear()
            if self.source is not None:
                self.publish_live(self.source())
            try:
                while not self.step() and not self.stop_event.is_set():
                    time.sleep(0.2)
                with self.lock:
                    self.status, self.error = 'conectado', None
                delay = 2
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode('utf-8', 'replace')[:200]
                if exc.code in (400, 401, 403):
                    self.token = None  # fuerza nuevo inicio de sesión
                self.fail(f'HTTP {exc.code}: {detail}', delay)
                delay = min(delay * 2, 120)
            except Exception as exc:
                self.fail(str(exc), delay)
                delay = min(delay * 2, 120)

    def fail(self, message, delay):
        with self.lock:
            self.status, self.error = 'sin conexión', message
        logging.warning('Firebase: %s (reintento en %s s)', message, delay)
        self.stop_event.wait(delay)
