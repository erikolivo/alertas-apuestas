"""
reporte_diario.py
------------------
Se corre 1 vez al día, a las 6am, ANTES de que arranque la Fase 1 del
día. Envía a Telegram los resultados de AYER: qué partidos seleccionados
ganó el favorito (✅) y cuáles no (❌), más cuántas peticiones de
API-Football quedaron usadas/disponibles.

No gasta cupo de API-Football — solo lee el archivo que ya dejó armado
cerrar_resultados.py (Fase 4) la noche anterior.
"""

import json
import datetime
from pathlib import Path

from telegram_utils import enviar_mensaje_telegram

DATA_DIR = Path(__file__).parent / "data"
DIR_HISTORIAL_DIAS = DATA_DIR / "historial_dias"
ZONA_HORARIA_LOCAL = datetime.timezone(datetime.timedelta(hours=-5))


def enviar_reporte():
    ayer = (datetime.datetime.now(ZONA_HORARIA_LOCAL).date() - datetime.timedelta(days=1)).isoformat()
    archivo_ayer = DIR_HISTORIAL_DIAS / f"{ayer}.json"

    if not archivo_ayer.exists():
        enviar_mensaje_telegram(f"📊 No hay datos archivados de ayer ({ayer}) todavía.")
        print(f"No existe {archivo_ayer}.")
        return

    datos = json.loads(archivo_ayer.read_text(encoding="utf-8"))
    partidos = datos.get("partidos", [])

    lineas = [f"📊 <b>Resultados de ayer ({ayer})</b>"]

    if not partidos:
        lineas.append("No hubo partidos seleccionados.")
    else:
        for p in partidos:
            if p.get("acierto") is True:
                marca = "✅"
            elif p.get("acierto") is False:
                marca = "❌"
            else:
                marca = "❓"
            resultado_txt = f" (resultado {p['resultado_final']})" if p.get("resultado_final") else " (sin resolver)"
            lineas.append(f"{marca} {p['partido']} — favorito: {p['favorito']}{resultado_txt}")

        resueltos = [p for p in partidos if p.get("acierto") is not None]
        aciertos = sum(1 for p in resueltos if p["acierto"])
        if resueltos:
            pct = round((aciertos / len(resueltos)) * 100, 1)
            lineas.append(f"\nTotal: {aciertos}/{len(resueltos)} aciertos ({pct}%)")

    usadas = datos.get("api_football_usadas")
    disponibles = datos.get("api_football_disponibles")
    if usadas is not None:
        lineas.append(f"\n🔧 Peticiones API-Football usadas ayer: {usadas}/100 (quedaron {disponibles} disponibles)")

    enviar_mensaje_telegram("\n".join(lineas))
    print(f"Reporte diario enviado ({len(partidos)} partidos).")


if __name__ == "__main__":
    enviar_reporte()
