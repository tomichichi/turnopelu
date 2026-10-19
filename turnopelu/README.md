# TurnoPelu

Web para que peluqueros publiquen sus turnos (lugar, horario, precio) y los clientes
los busquen, filtren y reserven. Python + Flask + SQLite.

## Ejecutar

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
python app.py
```

Abrir http://127.0.0.1:5000

La base `turnopelu.db` se crea sola la primera vez, con datos de ejemplo.

## Usuarios demo (clave `demo`)

- Peluqueros: `pelu1@demo.com`, `pelu2@demo.com`, `pelu3@demo.com`
- Cliente: `cliente@demo.com`

## Producción

Definir la variable de entorno `SECRET_KEY` con un valor largo y aleatorio, y usar un
servidor WSGI (por ejemplo `gunicorn app:app`) en lugar de `python app.py`.
