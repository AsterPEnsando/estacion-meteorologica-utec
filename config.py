import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
DEFAULTS = dict(port='COM13', baudrate=9600, storage_interval=60, stale_seconds=15, demo=False)

def load():
    try:
        return {**DEFAULTS, **json.loads((DATA / 'settings.json').read_text('utf-8'))}
    except (OSError, ValueError):
        return DEFAULTS.copy()

def save(settings):
    path = DATA / 'settings.tmp'
    path.write_text(json.dumps(settings, indent=2), encoding='utf-8')
    os.replace(path, DATA / 'settings.json')
