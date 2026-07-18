"""
monitor.py
----------
FASE 3, versión 3. Cambios de esta versión:

  - Frecuencia adaptativa: el workflow corre cada 5 min (el mínimo común
    entre 10 y 15), pero este script decide si "toca revisar ahora" según
    cuántos partidos están en ventana horaria en este momento: <=5
    partidos -> revisa cada 10 min, más de 5 -> cada 15 min.
  - Ya NO hay un filtro de marcador que decide si se piden estadísticas
    (antes solo se pedían si iba empatando/perdiendo por 1). Ahora se
    piden para TODOS los partidos en ventana, porque las alertas nuevas
    (ampliación de marcador, cuidado rival presiona) aplican incluso
    cuando el favorito va ganando. Esto gasta más cupo por partido
    revisado — es la contrapartida de "más partidos + más tipos de
    alerta" que hablamos.
  - "Memoria" del partido: cada revisión se guarda en
    historial_snapshots (dentro de partidos_hoy.json), no solo la
    última. Sirve para la alerta de "gol de cierre" (dominancia en TODO
    el partido, no solo el momento actual).
  - Sin límite de alertas por partido: cada revisión que cumpla algún
    escenario manda su alerta, aunque ya se haya mandado una parecida
    antes.
  - Cuando varios escenarios aplican a la vez, gana el de PROBABILIDAD
    DE GOL más alta calculada en ese momento (desempate por
    especificidad si hay empate exacto).

NOTA sobre el umbral de "probabilidad de gol inminente": quedó en 35%
por defecto (punto medio de las opciones discutidas, nunca confirmado
explícitamente) — UMBRAL_GOL_INMINENTE es el número a ajustar.
"""

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

from fetch_data import obtener_partidos_en_vivo, obtener_estadisticas_fixture
from telegram_utils import enviar_mensaje_telegram, escapar_html
from poisson_model import probabilidad_gol_inminente

DATA_DIR = Path(__file__).parent / "data"
ARCHIVO_PARTIDOS = DATA_DIR / "partidos_hoy.json"

MINUTOS_ANTES_DEL_INICIO = 10
MINUTOS_DURACION_MAXIMA = 130

UMBRAL_POCOS_PARTIDOS = 5
INTERVALO_POCOS = 10
INTERVALO_MUCHOS = 15

UMBRAL_GOL_INMINENTE = 0.35
MINUTO_TEMPRANO_1ER_TIEMPO = 30
VENTANA_GOL_DE_CIERRE = (75, 85)
DOMINANCIA_HISTORICA_MINIMA = 0.75
VENTANA_MINUTOS_PRESION = 15


def _en_ventana(kickoff_utc_iso, ahora=None):
    if not kickoff_utc_iso:
        return False
    ahora = ahora or datetime.now(timezone.utc)
    kickoff = datetime.fromisoformat(kickoff_utc_iso.replace("Z", "+00:00"))
    return (kickoff - timedelta(minutes=MINUTOS_ANTES_DEL_INICIO)) <= ahora <= \
           (kickoff + timedelta(minutes=MINUTOS_DURACION_MAXIMA))


def _toca_revisar_ahora(cantidad_en_ventana):
    intervalo = INTERVALO_POCOS if cantidad_en_ventana <= UMBRAL_POCOS_PARTIDOS else INTERVALO_MUCHOS
    minuto_actual = datetime.now(timezone.utc).minute
    return minuto_actual % intervalo == 0


def _valor_stat(stats_equipo, nombre_stat):
    for item in stats_equipo.get("statistics", []):
        if item.get("type") == nombre_stat:
            v = item.get("value")
            if v is None:
                return 0
            if isinstance(v, str) and v.endswith("%"):
                return float(v.replace("%", ""))
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0
    return 0


def _snapshot(stats_local, stats_visitante, minuto):
    return {
        "minuto": minuto,
        "tiros_local": _valor_stat(stats_local, "Total Shots"),
        "tiros_visitante": _valor_stat(stats_visitante, "Total Shots"),
        "tiros_puerta_local": _valor_stat(stats_local, "Shots on Goal"),
        "tiros_puerta_visitante": _valor_stat(stats_visitante, "Shots on Goal"),
        "corners_local": _valor_stat(stats_local, "Corner Kicks"),
        "corners_visitante": _valor_stat(stats_visitante, "Corner Kicks"),
        "posesion_local": _valor_stat(stats_local, "Ball Possession"),
        "posesion_visitante": _valor_stat(stats_visitante, "Ball Possession"),
        "rojas_local": _valor_stat(stats_local, "Red Cards"),
        "rojas_visitante": _valor_stat(stats_visitante, "Red Cards"),
    }


def _tiros_puerta_recientes(snap_actual, snap_anterior, campo):
    if not snap_anterior:
        return int(snap_actual[campo])
    return max(0, int(snap_actual[campo] - snap_anterior[campo]))


def _domina_snapshot(snap, favorito_es_local):
    if favorito_es_local:
        tiros_fav, tiros_riv = snap["tiros_local"], snap["tiros_visitante"]
        corn_fav, corn_riv = snap["corners_local"], snap["corners_visitante"]
    else:
        tiros_fav, tiros_riv = snap["tiros_visitante"], snap["tiros_local"]
        corn_fav, corn_riv = snap["corners_visitante"], snap["corners_local"]
    return (tiros_fav + corn_fav) > (tiros_riv + corn_riv)


def _dominancia_historica(historial_snapshots, favorito_es_local):
    if not historial_snapshots:
        return 0.0
    dominados = sum(1 for s in historial_snapshots if _domina_snapshot(s, favorito_es_local))
    return dominados / len(historial_snapshots)


def _link_busqueda(nombre_local, nombre_visitante, sitio):
    consulta = f"{nombre_local} vs {nombre_visitante} {sitio}".replace(" ", "+")
    return f"https://www.google.com/search?q={consulta}"


def _evaluar_escenarios(p, minuto, goles_local, goles_visitante, snap_actual, snap_anterior, historial_snapshots):
    favorito_es_local = p["favorito_es_local"]
    goles_favorito = goles_local if favorito_es_local else goles_visitante
    goles_rival = goles_visitante if favorito_es_local else goles_local
    diferencia = goles_favorito - goles_rival

    lambda_favorito = p["lambda_local"] if favorito_es_local else p["lambda_visitante"]
    lambda_rival = p["lambda_visitante"] if favorito_es_local else p["lambda_local"]

    tp_favorito = _tiros_puerta_recientes(
        snap_actual, snap_anterior, "tiros_puerta_local" if favorito_es_local else "tiros_puerta_visitante")
    tp_rival = _tiros_puerta_recientes(
        snap_actual, snap_anterior, "tiros_puerta_visitante" if favorito_es_local else "tiros_puerta_local")

    prob_gol_favorito = probabilidad_gol_inminente(lambda_favorito, tp_favorito, VENTANA_MINUTOS_PRESION)
    prob_gol_rival = probabilidad_gol_inminente(lambda_rival, tp_rival, VENTANA_MINUTOS_PRESION)

    escenarios = []

    if diferencia == -1 and prob_gol_favorito >= UMBRAL_GOL_INMINENTE:
        escenarios.append(("posible_empate", 1, prob_gol_favorito,
                            f"{p['favorito']} va perdiendo pero genera peligro (prob. de gol {prob_gol_favorito*100:.0f}%)"))

    if diferencia == 0:
        if minuto <= MINUTO_TEMPRANO_1ER_TIEMPO and goles_local == 0 and goles_visitante == 0 \
                and prob_gol_favorito >= UMBRAL_GOL_INMINENTE:
            escenarios.append(("gana_favorito_1er_tiempo", 3, prob_gol_favorito,
                                f"{p['favorito']} presionando fuerte y temprano, 0-0 (prob. de gol {prob_gol_favorito*100:.0f}%)"))
        elif prob_gol_favorito >= UMBRAL_GOL_INMINENTE:
            escenarios.append(("posible_victoria_favorito", 1, prob_gol_favorito,
                                f"{p['favorito']} sigue empatando pero presiona fuerte (prob. de gol {prob_gol_favorito*100:.0f}%)"))
        if prob_gol_rival >= UMBRAL_GOL_INMINENTE:
            escenarios.append(("posible_gol_no_favorito", 1, prob_gol_rival,
                                f"{p['no_favorito']} tomó el control del partido (prob. de gol {prob_gol_rival*100:.0f}%)"))

    if diferencia >= 1:
        if prob_gol_rival >= UMBRAL_GOL_INMINENTE:
            escenarios.append(("cuidado_rival_presiona", 1, prob_gol_rival,
                                f"{p['no_favorito']} presionando, puede complicar el resultado (prob. de gol {prob_gol_rival*100:.0f}%)"))
        if prob_gol_favorito >= UMBRAL_GOL_INMINENTE:
            escenarios.append(("ampliacion_marcador", 1, prob_gol_favorito,
                                f"{p['favorito']} sigue dominando, puede ampliar el marcador (prob. de gol {prob_gol_favorito*100:.0f}%)"))

    if VENTANA_GOL_DE_CIERRE[0] <= minuto <= VENTANA_GOL_DE_CIERRE[1] and diferencia in (0, -1):
        dominancia = _dominancia_historica(historial_snapshots, favorito_es_local)
        if dominancia >= DOMINANCIA_HISTORICA_MINIMA:
            escenarios.append(("gol_de_cierre", 3, prob_gol_favorito,
                                f"{p['favorito']} dominó el {dominancia*100:.0f}% del partido y quedan pocos minutos"))

    return escenarios


MENSAJES_POR_TIPO = {
    "posible_empate": "🟠 Posible empate",
    "posible_victoria_favorito": "🟢 Posible victoria de {favorito}",
    "gana_favorito_1er_tiempo": "⏱️ Gana {favorito} 1er tiempo",
    "posible_gol_no_favorito": "🔴 Posible gol del no favorito",
    "cuidado_rival_presiona": "⚠️ Cuidado, {no_favorito} presionando",
    "ampliacion_marcador": "🔵 Posible ampliación de marcador",
    "gol_de_cierre": "⏰ Posible gol de cierre",
}


def _construir_mensaje(p, tipo, motivo, minuto, goles_local, goles_visitante, snap_actual):
    # Escapamos aquí, en un solo punto, todo lo que puede traer texto de
    # nombres de equipo (favorito, no_favorito, local, visitante, y el
    # motivo -- que ya trae esos nombres insertados). Así, sin importar
    # qué símbolo raro traiga un nombre de equipo (ej. "&"), nunca vuelve
    # a romper el envío a Telegram.
    favorito = escapar_html(p["favorito"])
    no_favorito = escapar_html(p["no_favorito"])
    local = escapar_html(p["local"])
    visitante = escapar_html(p["visitante"])
    motivo_seguro = escapar_html(motivo)

    titulo = MENSAJES_POR_TIPO[tipo].format(favorito=favorito, no_favorito=no_favorito)
    link_besoccer = _link_busqueda(p["local"], p["visitante"], "besoccer")
    link_ecuabet = _link_busqueda(p["local"], p["visitante"], "ecuabet")

    return (
        f"{titulo}\n\n"
        f"{local} vs {visitante}\n"
        f"Minuto: {minuto} · Marcador: {goles_local}-{goles_visitante}\n\n"
        f"Motivo: {motivo_seguro}\n\n"
        f"📊 Estadísticas:\n"
        f"Tiros: {snap_actual['tiros_local']}-{snap_actual['tiros_visitante']} "
        f"(a puerta: {snap_actual['tiros_puerta_local']}-{snap_actual['tiros_puerta_visitante']})\n"
        f"Córners: {snap_actual['corners_local']}-{snap_actual['corners_visitante']}\n"
        f"Posesión: {snap_actual['posesion_local']:.0f}%-{snap_actual['posesion_visitante']:.0f}%\n\n"
        f"Cuota inicial ({favorito}): {p['cuota_inicial']} (prob. inicial {p['probabilidad_inicial']}%)\n\n"
        f"Ver en BeSoccer: {link_besoccer}\n"
        f"Ver en Ecuabet: {link_ecuabet}"
    )


def revisar():
    if not ARCHIVO_PARTIDOS.exists():
        print("No hay partidos_hoy.json todavía (Fase 1 no ha corrido con éxito hoy).")
        return

    datos = json.loads(ARCHIVO_PARTIDOS.read_text(encoding="utf-8"))
    con_fixture = [p for p in datos["partidos"] if p["fixture_id"] is not None]
    en_ventana = [p for p in con_fixture if _en_ventana(p.get("kickoff_utc"))]

    if not en_ventana:
        print("Ningún partido vigilado está en su ventana horaria ahora (0 peticiones gastadas).")
        return

    if not _toca_revisar_ahora(len(en_ventana)):
        print(f"Frecuencia adaptativa: con {len(en_ventana)} partido(s) en ventana, "
              f"todavía no toca revisar en este ciclo de 5 min.")
        return

    print(f"Consultando partidos en vivo ({len(en_ventana)} en ventana, 1 petición)...")
    en_vivo = obtener_partidos_en_vivo()
    en_vivo_por_id = {f["fixture"]["id"]: f for f in en_vivo}

    cambios = False

    for p in en_ventana:
        fixture = en_vivo_por_id.get(p["fixture_id"])
        if not fixture:
            continue

        minuto = fixture["fixture"]["status"].get("elapsed")
        if minuto is None:
            continue

        goles_local = fixture["goals"]["home"] or 0
        goles_visitante = fixture["goals"]["away"] or 0

        try:
            stats = obtener_estadisticas_fixture(p["fixture_id"])
        except Exception as e:
            print(f"[AVISO] No se pudieron obtener estadísticas de {p['partido']}: {e}")
            continue
        if len(stats) != 2:
            continue

        stats_local, stats_visitante = stats[0], stats[1]
        snap_actual = _snapshot(stats_local, stats_visitante, minuto)
        snap_anterior = p["historial_snapshots"][-1] if p["historial_snapshots"] else None

        escenarios = _evaluar_escenarios(
            p, minuto, goles_local, goles_visitante, snap_actual, snap_anterior, p["historial_snapshots"])

        p["historial_snapshots"].append(snap_actual)
        cambios = True

        if escenarios:
            escenarios.sort(key=lambda e: (e[2], e[1]), reverse=True)
            tipo, _especificidad, probabilidad, motivo = escenarios[0]

            mensaje = _construir_mensaje(p, tipo, motivo, minuto, goles_local, goles_visitante, snap_actual)
            if enviar_mensaje_telegram(mensaje):
                p["alertas_enviadas"].append({"tipo": tipo, "minuto": minuto, "probabilidad": round(probabilidad, 2)})
                print(f"Alerta '{tipo}' enviada: {p['partido']} (min {minuto}, prob {probabilidad*100:.0f}%)")

    if cambios:
        ARCHIVO_PARTIDOS.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print("Sin cambios en esta revisión.")


if __name__ == "__main__":
    revisar()
