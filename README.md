# Estación Meteorológica

## Firmware con tramas R / L / A / B / C

El receptor admite también el protocolo hexadecimal de `lectura_atmega.py`, sin modificar el AVR:

- `R=0202FF`: primer byte estado FC-37 (00 seco, 01 moderado, 02 intenso), siguientes dos bytes ADC hexadecimal. Los estados 1 y 2 se convierten en lluvia detectada.
- `L=02DF`: ADC LDR hexadecimal (735 en este ejemplo).
- `A=` seguido de 12 caracteres hexadecimales: seis bytes AHT20. Se comprueban los bits de calibración/ocupado y se convierten temperatura y humedad con las funciones originales.
- `C=` seguido de 48 caracteres hexadecimales: 24 bytes de calibración BMP280 little endian.
- `B=` seguido de 12 caracteres hexadecimales: presión y temperatura crudas BMP280, compensadas con la última calibración válida.

Cada trama termina en `\n`. Cada lectura válida actualiza el dashboard sin esperar a BMP280. `A=ERR`, `B=ERR` y `C=ERR` invalidan solo los sensores afectados; perder calibración también invalida BMP280. FC-37 y LDR continúan funcionando. Los valores parciales se almacenan respetando el intervalo configurado, con NULL en sensores ausentes. Las lecturas de cada sensor caducan según el umbral de datos recientes. Las calibraciones se reinician al reconectar para evitar usar coeficientes de otra sesión.

DS18B20 fue eliminado del proyecto: su columna queda vacía. La tarjeta y gráfica principal usan AHT20. La media en protocolo hexadecimal requiere AHT20 y BMP280 válidos. SQLite se migra automáticamente, sin borrar el historial, añadiendo `temp_aht`, `rain_level` y `rain_adc`; estos campos también se exportan a CSV.

Si el firmware sigue enviando `A=ERR`, `B=ERR` o `C=ERR`, el dashboard mostrará los errores reales. El receptor no puede recuperar lecturas que el hardware no está enviando: esos errores requieren revisar comunicación/alimentación del módulo sensor, mientras lluvia y luz permanecen operativas.

Aplicación local Flask + PySerial + SQLite. Interfaz en español, dos temas, cinco gráficas Chart.js locales, historial y exportación CSV. No requiere servicios en la nube.

## Ejecutar en Windows

Instala Python 3.10 o superior y marca **Add python.exe to PATH**. Desde PowerShell en esta carpeta:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

También puedes ejecutar `python app.py` si instalaste las dependencias en ese Python. Abre **http://localhost:5000**. Detén el servidor con Ctrl+C. Las dependencias solo necesitan internet al instalarlas; Chart.js y la tipografía se incluyen localmente. El servidor escucha únicamente en 127.0.0.1. No uses múltiples procesos ni el recargador de Flask: cada instancia abriría el receptor serial.

En este equipo también se preparó `iniciar.ps1`, que detecta el Python disponible y las dependencias locales en `.deps`. Puedes iniciarlo con `powershell -ExecutionPolicy Bypass -File .\iniciar.ps1` desde esta carpeta.

## Conectar HC-05

1. Empareja el HC-05 desde Windows y consulta su puerto COM saliente en el Administrador de dispositivos.
2. Abre Configuración en el dashboard. Por defecto: **COM13, 9600 baudios, 8N1** (el COM puede cambiar según el equipo). Cierra PuTTY, `PRUEBA.py` u otros monitores que ocupen el puerto.
3. La plataforma se detecta sola por el formato de la trama; no hay que cambiar nada al conmutar el arnés (apaga antes de cambiar conexiones).

### PSoC 5LP: una línea CSV por ciclo

```
28.96,29.67,75.39,1006.12,2800,0
```

Orden fijo: temperatura AHT20 °C, temperatura BMP280 °C, humedad %, presión hPa, promedio LDR (ADC entero 0–4095), estado de lluvia (0 seco, 1 moderado, 2 intenso). `nan` en los cuatro campos digitales indica sensor con fallo y se guarda como NULL; LDR y lluvia son obligatorios. Rangos: temperaturas −40..85, humedad 0..100, presión 300..1100. `PSOC5LP_READY` se ignora (no es dato ni error). La trama PSoC no incluye ADC crudo del FC-37: `rain_adc` queda vacío.

### ATmega328P: cinco líneas R/L/A/B/C por ciclo

Cada línea actualiza la interfaz en vivo, pero el registro en SQLite se hace solo cuando llega `C` y el ciclo contiene las cinco líneas desde `R`; los ciclos incompletos no se almacenan. Un `ERR` en A/B/C deja NULL solo en el sensor afectado.

### Campos normalizados

Cada registro guarda `platform` (`atmega328p`, `psoc5lp` o `demo`), `adc_max` (1023 o 4095) y `light_pct = ADC*100/adc_max`. La luz es **iluminación relativa, no lux**; los porcentajes AVR (divisor 10 kΩ) y PSoC (pull-down interno ≈5.6 kΩ) no son directamente comparables. `rain` (0/1) se conserva por compatibilidad; `rain_level` es el estado 0/1/2. La columna `temp_ds` es heredada del protocolo antiguo con DS18B20 y queda vacía.

El puerto abierto no implica recepción válida: se muestra «Sin datos recientes» hasta recibir una trama válida y cuando supera el umbral configurable (15 s inicialmente). La reconexión se intenta cada 3 s. El diagnóstico diferencia última recepción de último almacenamiento y conserva la última lectura visible aunque el enlace se desconecte.

## Captura e historial

Cada trama válida actualiza la interfaz aproximadamente cada segundo. Se almacena la primera trama válida y luego la primera recibida tras cada intervalo configurado (60 s inicialmente). No se reutilizan lecturas antiguas ni se generan registros durante una interrupción. Las marcas de tiempo incluyen zona horaria local; configura Windows con la hora correcta. SQLite usa WAL, conexiones por operación, índice temporal y marca de tiempo única. Los archivos se crean automáticamente en `data/`.

El modo real inicia siempre por defecto. Para probar sin hardware, activa **Modo demostración** en Configuración: aparece una etiqueta permanente, se pausa Bluetooth y los datos van exclusivamente a `data/demo.db`. Las consultas y exportaciones usan la base correspondiente al modo actual. Desactivarlo vuelve al receptor real. `data/meteorologia.db` nunca recibe datos demo. La configuración se conserva en `data/settings.json`, salvo que el modo demo se desactiva al reiniciar.

Los filtros temporales se aplican tanto a las gráficas como a la tabla y al CSV. La tabla tiene páginas de 25 registros. Las gráficas muestran hasta 2000 puntos distribuidos por intervalo para limitar el coste de dibujo; el CSV conserva todos los registros filtrados. El ADC de luz es una medida relativa, no lux; no se infiere día/noche ni pronósticos. Las tendencias comparan la lectura con el último registro disponible del intervalo seleccionado.

## Organización

- `app.py`: servidor y API (`/api/status`, `/api/settings`, `/api/history`, `/api/export`).
- `bluetooth.py`: parsers PSoC (CSV) y AVR (ciclo R/L/A/B/C), hilo serial, reconexión, demostración y política de captura.
- `firebase_sync.py`: envío opcional a Firebase (REST, sin dependencias extra).
- `docs/`: dashboard remoto estático para GitHub Pages.
- `firebase/database.rules.json`: reglas de seguridad de la base.
- `database.py`: SQLite y consultas parametrizadas.
- `config.py`: valores iniciales y configuración persistente.
- `templates/`, `static/`: interfaz y bibliotecas locales.
- `tests/test_app.py`: pruebas de parser, almacenamiento, separación de modos, API y CSV.

```powershell
python -m unittest discover -s tests -v
```

Chart.js 4.4.8 (MIT). Inter (SIL Open Font License). Licencias en `static/vendor/` y `static/assets/`.

## Visualización remota (Firebase + GitHub Pages)

```
HC-05 ──SPP──> laptop: app.py (SQLite local) ──HTTPS──> Firebase Realtime Database <──HTTPS── GitHub Pages (docs/)
```

GitHub Pages solo sirve archivos estáticos: no ejecuta Python ni accede al puerto COM. La laptop con `app.py` debe estar encendida, conectada al HC-05 y a Internet para que lleguen datos nuevos; el historial ya enviado sigue visible aunque la laptop se apague. La vista remota es de **solo lectura**: la plataforma y el COM se eligen en la laptop; en la web el selector de plataforma solo filtra datos.

Qué se publica: `<root>/live` (última lectura, estado del colector y latido con hora del servidor, cada ~3 s) y `<root>/history/<epoch_ms>` (solo los registros que se guardan en SQLite, según el intervalo de almacenamiento; 60 s por defecto). La clave por timestamp evita duplicados al reintentar. Sin Internet, el historial pendiente queda en cola en memoria (hasta 20 000 registros) y se reenvía al volver la conexión; si se cierra `app.py` antes, esos pendientes se pierden en la nube pero siguen en SQLite. El modo demostración nunca se publica.

### 1. Firebase (una vez)
1. En https://console.firebase.google.com crea un proyecto.
2. **Build → Realtime Database → Create database** (elige región y modo bloqueado). Copia la URL de la base.
3. **Build → Authentication → Sign-in method**: habilita *Correo electrónico/contraseña*. En **Users** crea un usuario solo para el colector y copia su **UID**.
4. **Realtime Database → Rules**: pega `firebase/database.rules.json`, reemplaza `REEMPLAZAR_CON_UID_DEL_COLECTOR` por el UID y publica. Resultado: cualquiera puede **leer** `estacion/`, solo ese usuario puede **escribir**; el resto de la base queda cerrado.
5. **Configuración del proyecto → General**: copia la *Clave de API web* (es pública; no da permisos por sí sola).

### 2. Colector local
Copia `.env.example` como `.env` y completa los valores (el archivo `.env` está en `.gitignore`; no lo subas). Inicia `app.py` como siempre: en *Estado del sistema* aparece «Nube Firebase: conectado» y los pendientes. Si falta `.env`, todo funciona igual en local.

### 3. GitHub Pages
1. Edita `docs/config.js` y pon `databaseURL` (solo la URL; ninguna clave).
2. Sube el proyecto al repositorio (revisa antes `git status`: no deben aparecer `.env`, `data/*.db`, `.deps/` ni `respaldo/`).
3. En GitHub: **Settings → Pages → Build and deployment → Deploy from a branch**, rama `main`, carpeta `/docs`. La URL será `https://<usuario>.github.io/<repositorio>/`.

Límites a considerar: el plan gratuito de Firebase tiene cuotas de almacenamiento y descarga (consultar las vigentes). Cada visitante consulta `live` cada 4 s y el historial cada 60 s; con 7 días a 60 s son ~10 000 registros por consulta (limitado a 5000). Ajusta `pollSeconds` en `config.js` o el intervalo de almacenamiento si hace falta. La lectura es pública: no publiques datos personales en la base.

Pruebas: `python -m unittest discover -s tests -v` (incluye `tests/test_firebase_sync.py`, que simula Firebase sin red).
