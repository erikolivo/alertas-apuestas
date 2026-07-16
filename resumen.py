"""
resumen.py
----------
FASE 2. Reintenta cada 15 min entre las 07:00 y las 08:30 (ver el
workflow) hasta lograr enviarlo, en vez de depender de un solo disparo
exacto a las 07:00 — GitHub Actions no garantiza que un cron disparado a
una hora fija corra justo a esa hora.
"""

import json
import datetime
from pathlib import Path

from telegram_utils import enviar_mensaje_telegram
from estado_diario import ya_se_hizo, marcar_hecho

ARCHIVO = Path(__file__).parent / "data" / "partidos_hoy.json"
ZONA_HORARIA_LOCAL = datetime.timezone(datetime.timedelta(hours=-5))


def _hora_local(hora_inicio_utc_iso):
    if not hora_inicio_utc_iso:
        return "?"
    try:
        dt_utc = datetime.datetime.fromisoformat(hora_inicio_utc_iso.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(ZONA_HORARIA_LOCAL)
        return dt_local.strftime("%H:%M")
    except Exception:
        return hora_inicio_utc_iso


def enviar_resumen():
    if ya_se_hizo("resumen"):
        print("El resumen de hoy ya se envió antes. Nada que hacer.")
        return

    if not ARCHIVO.exists():
        print("Fase 1 todavía no ha generado partidos_hoy.json. Se reintentará en el próximo ciclo.")
        return

    datos = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    partidos = datos.get("partidos", [])

    if not partidos:
        exito = enviar_mensaje_telegram(
            f"📋 Hoy no hay partidos con favorito de probabilidad inicial ≥ 60%."
        )
        if exito:
            marcar_hecho("resumen")
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

    exito = enviar_mensaje_telegram("\n".join(lineas))
    if exito:
        marcar_hecho("resumen")
    print(f"Resumen enviado con {len(partidos)} partido(s)." if exito else "Falló el envío del resumen.")


if __name__ == "__main__":
    enviar_resumen()
