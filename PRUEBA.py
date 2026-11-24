
import serial

PUERTO = "COM14"
VELOCIDAD = 9600

try:
    bt = serial.Serial(PUERTO, VELOCIDAD, timeout=2)

    print("ESTACION METEOROLOGICA")
    print("Puerto:", PUERTO)
    print("Velocidad:", VELOCIDAD)
    print("Esperando datos...\n")

    while True:
        dato = bt.readline()

        if dato:
            print(repr(dato))

except KeyboardInterrupt:
    print("\nConexion finalizada")

except serial.SerialException as e:
    print("Error:", e)

finally:
    if "bt" in locals() and bt.is_open:
        bt.close()
