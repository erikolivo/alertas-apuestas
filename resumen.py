"""
resumen.py
----------
FASE 2 de tu spec. Se corre 1 vez, a las 07:00. Envía a Telegram el
resumen de los partidos seleccionados hoy: total, hora, equipos, favorito
y cuota inicial. No gasta cupo de API-Football (solo lee lo que Fase 1
ya generó).
"""

import json
import datetime
from pathlib import Path

from telegram_utils import enviar_mensaje_telegram

ARCHIVO = Path(__file__).parent / "data" / "partidos_hoy.json"
ZONA_HORARIA_LOCAL = datetime.timezone(datetime.timedelta(hours=-5))  # Ecuador/Colombia/Perú


def _hora_local(hora_inicio_utc_iso):
    """Convierte la hora UTC del partido a tu hora local (UTC-5), para que
    el resumen sea legible sin tener que restar horas mentalmente."""
    if not hora_inicio_utc_iso:
        return "?"
    try:
        dt_utc = datetime.datetime.fromisoformat(hora_inicio_utc_iso.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(ZONA_HORARIA_LOCAL)
        return dt_local.strftime("%H:%M")
    except Exception:
        return hora_inicio_utc_iso


def enviar_resumen():
    if not ARCHIVO.exists():
        enviar_mensaje_telegram(
            "📋 Todavía no se ha generado la selección de partidos de hoy "
            "(puede que ClubElo esté teniendo problemas — Fase 1 lo seguirá "
            "reintentando cada 5 minutos)."
        )
        print("No hay partidos_hoy.json todavía.")
        return

    datos = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    partidos = datos.get("partidos", [])

    if not partidos:
        exito = enviar_mensaje_telegram(
            f"📋 Hoy no hay partidos con favorito de probabilidad inicial ≥ 60%."
        )
        print("Resumen enviado: 0 partidos hoy." if exito else "Falló el envío del resumen (ver error arriba).")
        return

    lineas = [f"📋 <b>{len(partidos)} partido(s) seleccionados hoy ({datos.get('fecha','')})</b> (horas en tu horario local)"]
    for p in partidos:
        hora = _hora_local(p.get("hora_inicio"))
        estado = "✅" if p["fixture_id"] else "⚠️ sin vigilancia en vivo"
        lineas.append(
            f"• {hora} — {p['partido']} · favorito: {p['favorito']} "
            f"(cuota inicial {p['cuota_inicial']}) {estado}"
        )

    enviar_mensaje_telegram("\n".join(lineas))
    print(f"Resumen enviado con {len(partidos)} partido(s).")


if __name__ == "__main__":
    enviar_resumen()
