"""
estado_diario.py
-----------------
GitHub Actions NO garantiza que un workflow programado a una hora exacta
corra justo a esa hora — puede atrasarse minutos u horas, o incluso
saltarse ese día por completo (es una limitación documentada de la
plataforma, no algo que podamos arreglar desde el código). Por eso, las
fases de "un solo disparo a una hora fija" (resumen 7am, cierre 23:30,
reporte 6am) pasan de "correr 1 vez a esa hora exacta" a "reintentar cada
15 min dentro de una ventana de 1-2 horas alrededor de esa hora", igual
que ya hacía Fase 1. Este módulo es el que permite que cada una sepa si
"ya se hizo hoy" o si le toca intentarlo de nuevo.
"""

import json
import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
ARCHIVO_ESTADO = DATA_DIR / "estado_diario.json"
ZONA_HORARIA_LOCAL = datetime.timezone(datetime.timedelta(hours=-5))


def _fecha_local_hoy():
    return datetime.datetime.now(ZONA_HORARIA_LOCAL).date().isoformat()


def _cargar():
    hoy = _fecha_local_hoy()
    if ARCHIVO_ESTADO.exists():
        try:
            estado = json.loads(ARCHIVO_ESTADO.read_text(encoding="utf-8"))
            if estado.get("fecha") == hoy:
                return estado
        except Exception:
            pass
    return {"fecha": hoy}


def ya_se_hizo(tarea):
    estado = _cargar()
    return estado.get(tarea, False) is True


def marcar_hecho(tarea):
    DATA_DIR.mkdir(exist_ok=True)
    estado = _cargar()
    estado[tarea] = True
    ARCHIVO_ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
