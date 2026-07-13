"""
seleccionar_partidos.py
------------------------
FASE 1, versión 4. Cambios de esta versión:

  - Umbral bajado de 74% a 60% de probabilidad inicial -> más partidos
    vigilados.
  - Se quitó el cruce con la predicción de API-Football (para ahorrar
    cupo; con el umbral más bajo hay más candidatos, y se prioriza el
    cupo para la vigilancia en vivo).
  - El Goal Index ya viene mezclado 60% forma reciente / 40% temporada
    completa (ver goal_index.py).

Sigue implementando "reintentar cada 5 min hasta lograrlo" de forma
eficiente: si ya se completó hoy, termina de inmediato.
"""

import json
import datetime
from pathlib import Path

from fetch_data import obtener_ranking_clubelo, obtener_fixtures_por_fecha, buscar_equipo_similar
from goal_index import construir_goal_index_global
from poisson_model import evaluar_favorito, cumple_filtro_cuota

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
ARCHIVO_SALIDA = DATA_DIR / "partidos_hoy.json"

ZONA_HORARIA_LOCAL = datetime.timezone(datetime.timedelta(hours=-5))


def fecha_local_hoy():
    return datetime.datetime.now(ZONA_HORARIA_LOCAL).date().isoformat()


def ya_se_completo_hoy():
    if not ARCHIVO_SALIDA.exists():
        return False
    try:
        datos = json.loads(ARCHIVO_SALIDA.read_text(encoding="utf-8"))
        return datos.get("fecha") == fecha_local_hoy()
    except Exception:
        return False


def seleccionar():
    if ya_se_completo_hoy():
        print("La selección de hoy ya se generó antes. Nada que hacer (0 peticiones gastadas).")
        return

    hoy = fecha_local_hoy()
    print(f"Buscando partidos de hoy ({hoy})...")

    fixtures_api = obtener_fixtures_por_fecha(hoy)
    print(f"Partidos de hoy en API-Football (todas las ligas): {len(fixtures_api)}")

    ranking = obtener_ranking_clubelo(hoy)
    if not ranking:
        ayer = (datetime.datetime.now(ZONA_HORARIA_LOCAL).date() - datetime.timedelta(days=1)).isoformat()
        print(f"[AVISO] Ranking de hoy vacío, probando con el de ayer ({ayer})...")
        ranking = obtener_ranking_clubelo(ayer)

    elo_por_equipo = {}
    for fila in ranking:
        try:
            elo_por_equipo[fila["Club"]] = float(fila["Elo"])
        except (KeyError, ValueError):
            continue
    nombres_clubelo = list(elo_por_equipo.keys())
    print(f"Equipos con Elo disponible en ClubElo: {len(nombres_clubelo)}")

    print("Construyendo Goal Index (38 ligas, forma reciente + temporada)...")
    goal_index = construir_goal_index_global()
    print(f"Equipos con Goal Index disponible: {len(goal_index)}")

    seleccionados = []
    sin_elo = 0

    for f in fixtures_api:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]

        cand_home = buscar_equipo_similar(home, nombres_clubelo, n=1, corte=0.6)
        cand_away = buscar_equipo_similar(away, nombres_clubelo, n=1, corte=0.6)
        if not cand_home or not cand_away:
            sin_elo += 1
            continue

        elo_home = elo_por_equipo[cand_home[0]]
        elo_away = elo_por_equipo[cand_away[0]]

        gi_home = gi_away = None
        cand_gi_home = buscar_equipo_similar(home, list(goal_index.keys()), n=1, corte=0.6)
        cand_gi_away = buscar_equipo_similar(away, list(goal_index.keys()), n=1, corte=0.6)
        if cand_gi_home:
            gi_home = goal_index[cand_gi_home[0]]["goal_index"]
        if cand_gi_away:
            gi_away = goal_index[cand_gi_away[0]]["goal_index"]

        evaluacion = evaluar_favorito(elo_home, elo_away, gi_home, gi_away)
        if not cumple_filtro_cuota(evaluacion):
            continue

        favorito_nombre = home if evaluacion["lado"] == "local" else away
        no_favorito_nombre = away if evaluacion["lado"] == "local" else home

        seleccionados.append({
            "partido": f"{home} vs {away}",
            "local": home,
            "visitante": away,
            "favorito": favorito_nombre,
            "no_favorito": no_favorito_nombre,
            "favorito_es_local": evaluacion["lado"] == "local",
            "cuota_inicial": evaluacion["cuota_inicial"],
            "probabilidad_inicial": round(evaluacion["probabilidad"] * 100, 1),
            "lambda_local": evaluacion["lambda_local"],
            "lambda_visitante": evaluacion["lambda_visitante"],
            "goal_index_disponible": gi_home is not None and gi_away is not None,
            "hora_inicio": f["fixture"]["date"],
            "fixture_id": f["fixture"]["id"],
            "kickoff_utc": f["fixture"]["date"],
            "resultado_final": None,
            "acierto": None,
            "historial_snapshots": [],
            "alertas_enviadas": [],
        })

    print(f"Partidos sin Elo disponible en ClubElo (no evaluables): {sin_elo}")

    ARCHIVO_SALIDA.write_text(
        json.dumps({"fecha": hoy, "partidos": seleccionados}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Guardado en {ARCHIVO_SALIDA}. {len(seleccionados)} partidos seleccionados "
          f"(probabilidad inicial >= 60%).")


if __name__ == "__main__":
    seleccionar()
