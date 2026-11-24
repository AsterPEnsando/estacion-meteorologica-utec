"""Decodificación de las tramas hexadecimales del firmware ATmega328P (R/L/A/B/C)."""
import math
import struct
import time

AVR_ADC_MAX = 1023


def light_fields(adc, adc_max):
    """Iluminación relativa = ADC*100/máximo. No son lux ni W/m²."""
    return dict(adc_max=adc_max, light_pct=round(adc * 100 / adc_max, 2) if adc is not None else None)


def convertir_aht(datos):
    h = (datos[1] << 12) | (datos[2] << 4) | (datos[3] >> 4)
    t = ((datos[3] & 15) << 16) | (datos[4] << 8) | datos[5]
    return t * 200.0 / 1048576.0 - 50.0, h * 100.0 / 1048576.0


def convertir_bmp(datos, cal):
    T1,T2,T3,P1,P2,P3,P4,P5,P6,P7,P8,P9 = struct.unpack('<HhhH' + 'h' * 8, cal)
    ap = (datos[0]<<12) | (datos[1]<<4) | (datos[2]>>4)
    at = (datos[3]<<12) | (datos[4]<<4) | (datos[5]>>4)
    if ap == 0x80000 or at == 0x80000 or P1 == 0:
        raise ValueError('Datos BMP280 inválidos')
    v1 = (at/16384.0 - T1/1024.0) * T2
    v2 = ((at/131072.0 - T1/8192.0)**2) * T3
    fino = v1 + v2
    temperatura = fino / 5120.0
    v1 = fino/2.0 - 64000.0
    v2 = v1*v1*P6/32768.0
    v2 += v1*P5*2.0
    v2 = v2/4.0 + P4*65536.0
    v1 = (P3*v1*v1/524288.0 + P2*v1)/524288.0
    v1 = (1.0 + v1/32768.0)*P1
    if v1 == 0:
        raise ValueError('Calibración BMP280 inválida')
    p = (1048576.0 - ap - v2/4096.0)*6250.0/v1
    v1 = P9*p*p/2147483648.0
    v2 = p*P8/32768.0
    p += (v1+v2+P7)/16.0
    return temperatura, p/100.0


class SensorProtocol:
    groups = {'R': ('rain','rain_level','rain_adc'), 'L': ('light',),
              'A': ('temp_aht','humidity'), 'B': ('temp_bmp','pressure')}

    def __init__(self):
        self.calibration = None
        self.values = {}
        self.updated = {}
        self.errors = {}

    def invalidate(self, kind, message):
        if kind == 'C':
            self.calibration = None
            self.invalidate('B', 'Sin calibración BMP280')
        for key in self.groups.get(kind, ()):
            self.values.pop(key, None)
        self.updated.pop(kind, None)
        self.errors[kind] = message

    def snapshot(self, stale_seconds):
        for kind, stamp in list(self.updated.items()):
            if time.monotonic() - stamp > stale_seconds:
                self.invalidate(kind, 'Sin lectura reciente')
        result = dict.fromkeys(('temp_ds','temp_aht','temp_bmp','humidity','pressure','light','rain','rain_level','rain_adc'))
        result.update(self.values)
        a, b = result['temp_aht'], result['temp_bmp']
        result['temp_avg'] = (a+b)/2 if a is not None and b is not None else None
        result['platform'] = 'atmega328p'
        result.update(light_fields(result['light'], AVR_ADC_MAX))
        return result

    def feed(self, line, stale_seconds):
        kind, value = (part.strip() for part in line.split('=', 1))
        if kind not in (*self.groups, 'C'):
            raise ValueError('Tipo de trama desconocido')
        try:
            if value == 'ERR':
                raise ValueError('Error de comunicación del sensor')
            expected = {'R':6,'L':4,'A':12,'B':12,'C':48}[kind]
            if len(value) != expected or any(c not in '0123456789abcdefABCDEF' for c in value):
                raise ValueError('Longitud o contenido hexadecimal inválido')
            raw = bytes.fromhex(value)
            if kind == 'C':
                if struct.unpack_from('<H', raw, 6)[0] == 0:
                    raise ValueError('Calibración BMP280 inválida: P1=0')
                self.calibration = raw
                self.errors.pop('C', None)
                return None
            if kind == 'R':
                level, adc = raw[0], int.from_bytes(raw[1:], 'big')
                if level not in (0,1,2) or adc > 1023:
                    raise ValueError('FC-37 fuera de rango')
                values = (int(level > 0), level, adc)
            elif kind == 'L':
                values = (int(value, 16),)
                if values[0] > 1023:
                    raise ValueError('LDR fuera de rango')
            elif kind == 'A':
                if raw[0] & 0x88 != 0x08:
                    raise ValueError('AHT20 ocupado o sin calibrar')
                values = convertir_aht(raw)
                if not -40 <= values[0] <= 85 or not 0 <= values[1] <= 100:
                    raise ValueError('AHT20 fuera de rango')
            else:
                if self.calibration is None:
                    raise ValueError('Sin calibración BMP280')
                values = convertir_bmp(raw, self.calibration)
                if not all(math.isfinite(v) for v in values) or not -40 <= values[0] <= 85 or not 300 <= values[1] <= 1100:
                    raise ValueError('BMP280 fuera de rango')
            self.values.update(zip(self.groups[kind], values))
            self.updated[kind] = time.monotonic()
            self.errors.pop(kind, None)
            return self.snapshot(stale_seconds)
        except ValueError as exc:
            self.invalidate(kind, str(exc))
            raise ValueError(f'{kind}: {exc}') from exc
