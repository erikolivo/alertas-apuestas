"""
seleccionar_partidos.py
------------------------
FASE 1, versión 5. Cambios de esta versión:

  - CORRECCIÓN IMPORTANTE: se detectó (con varios casos reales: Vestri,
    Ceara/Athletic Club, Maitland/Fremantle City) que el emparejamiento
    de nombres con ClubElo solo comparaba qué tan PARECIDO sonaba el
    nombre, sin verificar que fuera del mismo país. Con miles de clubes
    en ClubElo, nombres cortos o genéricos (ej. "Maitland", que existe
    en Australia y en otros países) podían emparejarse por accidente con
    un club de un país distinto, dando un Elo completamente equivocado.
    Ahora se filtra primero por país (usando el país del partido, de
    API-Football, convertido al código de 3 letras que usa ClubElo)
    antes de buscar el nombre más parecido dentro de ESE país.
  - Umbral bajado de 74% a 60% de probabilidad inicial.
  - El Goal Index viene mezclado 60% forma reciente / 40% temporada.

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

# Mapeo país (como lo da API-Football, en texto) -> código de 3 letras que
# usa ClubElo. No es exhaustivo — cuando un país no está aquí, seguimos
# con el emparejamiento global sin filtrar (mejor eso que descartar el
# partido), pero queda marcado (ver "pais_verificado" en cada partido
# guardado) para saber cuáles emparejamientos son menos confiables.
PAIS_A_CODIGO_CLUBELO = {
    "England": "ENG", "Scotland": "SCO", "Wales": "WAL", "Northern-Ireland": "NIR",
    "Spain": "ESP", "Italy": "ITA", "Germany": "GER", "France": "FRA",
    "Portugal": "POR", "Netherlands": "NED", "Belgium": "BEL", "Turkey": "TUR",
    "Greece": "GRE", "Russia": "RUS", "Ukraine": "UKR", "Poland": "POL",
    "Austria": "AUT", "Switzerland": "SUI", "Sweden": "SWE", "Norway": "NOR",
    "Denmark": "DEN", "Finland": "FIN", "Iceland": "ISL", "Ireland": "IRL",
    "Croatia": "CRO", "Serbia": "SRB", "Romania": "ROU", "Bulgaria": "BUL",
    "Hungary": "HUN", "Czech-Republic": "CZE", "Slovakia": "SVK", "Slovenia": "SVN",
    "Bosnia": "BIH", "Israel": "ISR", "Cyprus": "CYP", "Luxembourg": "LUX",
    "Brazil": "BRA", "Argentina": "ARG", "Mexico": "MEX", "USA": "USA",
    "Colombia": "COL", "Chile": "CHI", "Peru": "PER", "Uruguay": "URU",
    "Ecuador": "ECU", "Paraguay": "PAR", "Bolivia": "BOL", "Venezuela": "VEN",
    "Australia": "AUS", "Japan": "JPN", "South-Korea": "KOR", "China": "CHN",
    "Saudi-Arabia": "KSA", "Qatar": "QAT", "Egypt": "EGY", "South-Africa": "RSA",
}


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

    # IMPORTANTE: el Elo se guarda por (país, nombre), NO solo por nombre.
    # Si solo se indexara por nombre, dos clubes homónimos de países
    # distintos (ej. dos "Maitland") se pisarían entre sí en el
    # diccionario, y quedaría solo el último que se haya leído del CSV —
    # sin importar cuál país es el correcto. Con esto, cada país tiene su
    # propia tabla de Elo separada.
    elo_por_pais = {}       # {codigo_pais: {nombre_club: elo}}
    elo_global_ultimo = {}  # nombre_club: elo (para el respaldo sin país verificado — puede pisarse entre países, es sabido y aceptado solo como último recurso)

    for fila in ranking:
        try:
            club = fila["Club"]
            elo = float(fila["Elo"])
            pais_club = fila.get("Country", "")
            elo_por_pais.setdefault(pais_club, {})[club] = elo
            elo_global_ultimo[club] = elo
        except (KeyError, ValueError):
            continue

    nombres_clubelo = list(elo_global_ultimo.keys())
    print(f"Equipos con Elo disponible en ClubElo: {len(nombres_clubelo)}")

    print("Construyendo Goal Index (38 ligas, forma reciente + temporada)...")
    goal_index = construir_goal_index_global()
    print(f"Equipos con Goal Index disponible: {len(goal_index)}")

    seleccionados = []
    sin_elo = 0
    sin_pais_verificado = 0

    for f in fixtures_api:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]

        pais_partido = f.get("league", {}).get("country", "")
        codigo_clubelo = PAIS_A_CODIGO_CLUBELO.get(pais_partido)
        pais_verificado = False

        if codigo_clubelo and codigo_clubelo in elo_por_pais:
            # Filtramos primero por país: así "Maitland" en Australia ya
            # no puede emparejarse por accidente con un "Maitland" de
            # otro país que tenga un Elo completamente distinto.
            tabla_pais = elo_por_pais[codigo_clubelo]
            candidatos_del_pais = list(tabla_pais.keys())
            cand_home = buscar_equipo_similar(home, candidatos_del_pais, n=1, corte=0.6)
            cand_away = buscar_equipo_similar(away, candidatos_del_pais, n=1, corte=0.6)
            pais_verificado = True
        else:
            # País no cubierto en nuestro mapeo (o ClubElo no tiene ese
            # país) — seguimos con el emparejamiento global, sin
            # filtrar, pero lo marcamos como menos confiable.
            tabla_pais = elo_global_ultimo
            cand_home = buscar_equipo_similar(home, nombres_clubelo, n=1, corte=0.6)
            cand_away = buscar_equipo_similar(away, nombres_clubelo, n=1, corte=0.6)
            sin_pais_verificado += 1

        if not cand_home or not cand_away:
            sin_elo += 1
            continue

        elo_home = tabla_pais[cand_home[0]]
        elo_away = tabla_pais[cand_away[0]]

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
            "pais_verificado": pais_verificado,
            "hora_inicio": f["fixture"]["date"],
            "fixture_id": f["fixture"]["id"],
            "kickoff_utc": f["fixture"]["date"],
            "resultado_final": None,
            "acierto": None,
            "historial_snapshots": [],
            "alertas_enviadas": [],
        })

    print(f"Partidos sin Elo disponible en ClubElo (no evaluables): {sin_elo}")
    print(f"Partidos evaluados SIN poder verificar el país (país no cubierto en el mapeo): {sin_pais_verificado}")

    ARCHIVO_SALIDA.write_text(
        json.dumps({"fecha": hoy, "partidos": seleccionados}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    sin_verificar_seleccionados = sum(1 for p in seleccionados if not p["pais_verificado"])
    print(f"Guardado en {ARCHIVO_SALIDA}. {len(seleccionados)} partidos seleccionados "
          f"(probabilidad inicial >= 60%), de los cuales {sin_verificar_seleccionados} "
          f"sin verificación de país (revisar con más cuidado).")


if __name__ == "__main__":
    seleccionar()
