"""
reporte_diario.py
------------------
Reintenta cada 15 min entre las 06:00 y las 07:00 (ver el workflow) hasta
lograrlo, en vez de depender de un solo disparo exacto a las 6am.

Envía a Telegram los resultados de AYER: qué partidos seleccionados ganó
el favorito (✅) y cuáles no (❌), más cuántas peticiones de API-Football
quedaron usadas/disponibles.
"""

import json
import datetime
from pathlib import Path

from telegram_utils import enviar_mensaje_telegram
from estado_diario import ya_se_hizo, marcar_hecho

DATA_DIR = Path(__file__).parent / "data"
DIR_HISTORIAL_DIAS = DATA_DIR / "historial_dias"
ZONA_HORARIA_LOCAL = datetime.timezone(datetime.timedelta(hours=-5))


def enviar_reporte():
    if ya_se_hizo("reporte"):
        print("El reporte de hoy ya se envió antes. Nada que hacer.")
        return

    ayer = (datetime.datetime.now(ZONA_HORARIA_LOCAL).date() - datetime.timedelta(days=1)).isoformat()
    archivo_ayer = DIR_HISTORIAL_DIAS / f"{ayer}.json"

    if not archivo_ayer.exists():
        print(f"Todavía no existe {archivo_ayer} (Fase 4 de ayer puede seguir reintentando). "
              f"Se reintentará en el próximo ciclo.")
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

    exito = enviar_mensaje_telegram("\n".join(lineas))
    if exito:
        marcar_hecho("reporte")
    print(f"Reporte diario enviado ({len(partidos)} partidos)." if exito else "Falló el envío del reporte.")


if __name__ == "__main__":
    enviar_reporte()
