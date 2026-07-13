"""
cuota_api_football.py
----------------------
Lleva la cuenta de cuántas peticiones se han usado hoy contra el límite
gratuito de 100/día de API-Football. NO cambia entre cuentas — se
descartó esa idea porque los términos de servicio de API-Football
prohíben explícitamente tener varias cuentas para aumentar el límite
gratuito.

Se usa para el reporte de las 6am ("cuántas consultas quedaron
disponibles").
"""

import json
import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
ARCHIVO_USO = DATA_DIR / "uso_api_football.json"
LIMITE_DIARIO = 100


def _fecha_local_hoy():
    zona = datetime.timezone(datetime.timedelta(hours=-5))
    return datetime.datetime.now(zona).date().isoformat()


def _cargar_estado():
    hoy = _fecha_local_hoy()
    if ARCHIVO_USO.exists():
        try:
            estado = json.loads(ARCHIVO_USO.read_text(encoding="utf-8"))
            if estado.get("fecha") == hoy:
                return estado
        except Exception:
            pass
    return {"fecha": hoy, "usadas": 0}


def _guardar_estado(estado):
    DATA_DIR.mkdir(exist_ok=True)
    ARCHIVO_USO.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


def registrar_uso():
    estado = _cargar_estado()
    estado["usadas"] += 1
    _guardar_estado(estado)


def uso_de_hoy():
    estado = _cargar_estado()
    usadas = estado["usadas"]
    return usadas, max(0, LIMITE_DIARIO - usadas)
