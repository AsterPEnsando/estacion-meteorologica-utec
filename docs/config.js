// Configuración pública del dashboard remoto. No pongas aquí contraseñas ni claves privadas:
// la lectura es pública por REST y la escritura la protegen las reglas de Firebase.
window.ESTACION_CONFIG = {
  databaseURL: 'https://data-base-em-default-rtdb.firebaseio.com',
  root: 'estacion',         // igual que FIREBASE_ROOT del colector
  pollSeconds: 4,           // frecuencia de consulta del dato en vivo
  offlineSeconds: 30        // sin latido del colector durante este tiempo = desconectado
};
