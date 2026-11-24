import atexit
import csv
import io
import logging
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template, request, Response
from serial.tools import list_ports
import config
from database import Database, FIELDS
from bluetooth import Receiver
from firebase_sync import FirebaseSync

def create_app(start_receiver=True, data_dir=None, sync=None):
    app = Flask(__name__)
    real = Database(data_dir / 'meteorologia.db' if data_dir else None)
    demo = Database((data_dir or config.DATA) / 'demo.db')
    settings = config.load()
    settings['demo'] = False  # Siempre iniciar en modo real.
    if sync is None and start_receiver:
        sync = FirebaseSync()
    receiver = Receiver(settings, real, demo, sync)
    app.extensions['receiver'] = receiver
    if start_receiver:
        receiver.thread.start()
        atexit.register(receiver.stop_event.set)
        if sync is not None and sync.enabled:
            sync.source = lambda: {**receiver.snapshot(), 'demo': receiver.snapshot()['settings']['demo']}
            sync.thread.start()
            atexit.register(sync.stop_event.set)
            logging.info('Sincronización Firebase activa')
        else:
            logging.info('Firebase desactivado: faltan datos en .env')

    @app.before_request
    def protect_local_mutations():
        if request.method == 'POST' and (request.headers.get('Origin') not in (None, request.host_url.rstrip('/')) or not request.is_json):
            return jsonify(error='Solicitud de configuración no permitida'), 403

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/status')
    def status():
        result = receiver.snapshot()
        try:
            result.update(receiver.dbs[result['settings']['demo']].stats())
        except Exception:
            result.update(count=0,last_stored=None,storage_error='No se puede consultar SQLite')
        return jsonify(result)

    @app.route('/api/settings', methods=['GET','POST'])
    def settings_route():
        if request.method == 'GET':
            return jsonify(settings=receiver.snapshot()['settings'], ports=[p.device for p in list_ports.comports()])
        body = request.get_json()
        try:
            new = dict(port=str(body['port']).strip(),baudrate=int(body['baudrate']),storage_interval=int(body['storage_interval']),stale_seconds=int(body['stale_seconds']),demo=body['demo'])
            if not new['port'] or len(new['port'])>100 or not 300<=new['baudrate']<=1000000 or not 1<=new['storage_interval']<=86400 or not 2<=new['stale_seconds']<=3600 or type(new['demo']) is not bool:
                raise ValueError()
            config.save(new)
            receiver.configure(new)
            return jsonify(ok=True)
        except (KeyError,TypeError,ValueError):
            return jsonify(error='Revisa el puerto, baud rate e intervalos permitidos.'),400
        except OSError:
            return jsonify(error='No se pudo guardar la configuración.'),500

    def get_rows(export=False):
        now = datetime.now().astimezone()
        hours = int(request.args.get('hours',24))
        start = datetime.fromisoformat(request.args['start']).astimezone() if request.args.get('start') else now-timedelta(hours=hours)
        end = datetime.fromisoformat(request.args['end']).astimezone() if request.args.get('end') else now
        if start>end or not 1<=hours<=87600:
            raise ValueError('Intervalo inválido')
        page = max(1,int(request.args.get('page',1)))
        chart = request.args.get('chart') == '1'
        db = receiver.dbs[receiver.snapshot()['settings']['demo']]
        rows,count = db.query(start.isoformat(timespec='milliseconds'),end.isoformat(timespec='milliseconds'),page,25,request.args.get('order','desc'),export or chart)
        if chart:
            rows = rows[::-1] if request.args.get('order','desc') != 'asc' else rows
            # Conserva extremos y limita el coste de dibujo para intervalos extensos.
            if len(rows)>2000:
                step = (len(rows)-1)/1999
                rows = [rows[round(i*step)] for i in range(2000)]
        return rows,count,page

    @app.get('/api/history')
    def history():
        try:
            rows,count,page = get_rows()
            return jsonify(rows=rows,count=count,page=page)
        except (ValueError,OverflowError):
            return jsonify(error='El intervalo de fechas no es válido.'),400

    @app.get('/api/export')
    def export():
        try:
            rows,_,_ = get_rows(True)
        except (ValueError,OverflowError):
            return jsonify(error='El intervalo de fechas no es válido.'),400
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['Fecha y hora','Temperatura DS (°C)','Temperatura BMP (°C)','Promedio (°C)','Humedad (%)','Presión (hPa)','Luz (ADC)','Lluvia detectada (0/1)','Temperatura AHT20 (°C)','Estado lluvia (0 seco/1 moderado/2 intenso)','FC-37 ADC','Plataforma','ADC máximo','Luz relativa (%)'])
        for row in rows:
            writer.writerow([row['timestamp']]+[row[k] for k in FIELDS])
        name = 'demo' if receiver.snapshot()['settings']['demo'] else 'real'
        return Response('\ufeff'+output.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename=meteorologia-{name}.csv'})
    return app

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    create_app().run(host='127.0.0.1',port=5000,debug=False,threaded=True)
