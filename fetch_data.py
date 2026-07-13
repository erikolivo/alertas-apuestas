"""
fetch_data.py
--------------
Descarga datos crudos de fuentes gratuitas:

- ClubElo (clubes):     http://api.clubelo.com
- Eloratings (selecciones): https://www.eloratings.net
- football-data.co.uk (resultados históricos por liga, para el "goal index" de clubes)

IMPORTANTE (léelo antes de correr en producción):
Estas fuentes NO tienen un contrato de API estable/documentado oficialmente
(salvo ClubElo, que sí documenta su formato en http://clubelo.com/API).
Por eso este archivo aísla TODAS las llamadas de red en funciones pequeñas:
si un formato cambia, solo hay que tocar una función aquí, no todo el proyecto.

Si alguna función falla, revisa:
  1. Que la URL siga respondiendo igual (ábrela en el navegador).
  2. Que el nombre de equipo que buscas esté escrito como en la fuente
     (usa buscar_equipo_similar() para encontrar coincidencias aproximadas).
"""

import csv
import io
import os
import time
import difflib
import requests
from pathlib import Path

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EloPredictorBot/1.0)"}


def _get_con_reintentos(url, headers=None, params=None, timeout=35, intentos=5):
    """
    Wrapper de requests.get() con reintentos y backoff. ClubElo en
    particular es un sitio pequeño que documenta públicamente que a veces
    se sobrecarga ("Site overloaded, only cached pages available"). Con 1
    solo intento eso se traduce en una falla del workflow. Con esto, si un
    intento falla por timeout o error de conexión, esperamos un poco más
    cada vez y reintentamos, hasta 'intentos' veces, antes de rendirnos.
    """
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=timeout)
            r.raise_for_status()
            return r
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            ultimo_error = e
            print(f"[AVISO] Intento {intento}/{intentos} falló para {url}: {e}")
            if intento < intentos:
                time.sleep(8 * intento)  # 8s, 16s, 24s, 32s... backoff creciente
    raise ultimo_error

# API-Football (api-sports.io) - se usa SOLO para la vigilancia en vivo.
# Plan gratis: 100 peticiones/día. Por eso todas las funciones de abajo
# están diseñadas para hacer 1 sola petición por revisión, sin importar
# cuántos partidos estés vigilando.
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY", "")
API_FOOTBALL_BASE = "https://v3.football.api-sports.io"


def _headers_api_football():
    return {"x-apisports-key": API_FOOTBALL_KEY}


def _api_football_request(endpoint, params=None, timeout=20):
    """
    Punto único por donde pasan TODAS las llamadas a API-Football.
    Usa una sola cuenta (API_FOOTBALL_KEY) y registra el uso del día vía
    cuota_api_football.py, para poder reportarlo en el resumen de las 6am.
    """
    from cuota_api_football import registrar_uso

    r = requests.get(
        f"{API_FOOTBALL_BASE}/{endpoint}",
        headers=_headers_api_football(),
        params=params,
        timeout=timeout,
    )
    r.raise_for_status()
    registrar_uso()
    return r.json().get("response", [])


# ---------------------------------------------------------------------------
# 1. CLUB ELO  (clubes de fútbol)
# ---------------------------------------------------------------------------

CACHE_FIXTURES = Path(__file__).parent / "data" / "_cache_fixtures.csv"
CACHE_FIXTURES.parent.mkdir(exist_ok=True)


def obtener_fixtures_clubelo():
    """
    Devuelve la lista de próximos partidos de clubes con las probabilidades
    YA calculadas por ClubElo (1X2 y probabilidad de cada resultado exacto).
    Fuente: http://api.clubelo.com/Fixtures

    Si ClubElo falla incluso tras todos los reintentos (le pasa de vez en
    cuando: es un sitio pequeño que se sobrecarga), usamos el último
    resultado que sí funcionó, guardado en caché, en vez de fallar por
    completo. Así el sistema sigue funcionando con datos un poco
    desactualizados en vez de no producir nada ese día.
    """
    url = "http://api.clubelo.com/Fixtures"
    try:
        r = _get_con_reintentos(url, headers=HEADERS)
        CACHE_FIXTURES.write_text(r.text, encoding="utf-8")
        return list(csv.DictReader(io.StringIO(r.text)))
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        if CACHE_FIXTURES.exists():
            print(f"[AVISO] ClubElo no respondió tras varios intentos ({e}). "
                  f"Usando el último resultado exitoso guardado en caché "
                  f"(puede tener hasta unas horas de antigüedad).")
            texto_cache = CACHE_FIXTURES.read_text(encoding="utf-8")
            return list(csv.DictReader(io.StringIO(texto_cache)))
        print("[AVISO] ClubElo no respondió y no hay caché previo disponible. "
              "No se pueden generar predicciones esta vez.")
        raise


CACHE_RANKING = Path(__file__).parent / "data" / "_cache_ranking.csv"


def obtener_ranking_clubelo(fecha="today"):
    """
    Devuelve el ranking Elo completo de clubes para una fecha (YYYY-MM-DD)
    o 'today' para el más reciente. Con el mismo respaldo de caché que
    obtener_fixtures_clubelo(): si ClubElo falla tras todos los
    reintentos, usa el último ranking que sí se descargó con éxito.
    """
    url = f"http://api.clubelo.com/{fecha}"
    try:
        r = _get_con_reintentos(url, headers=HEADERS)
        CACHE_RANKING.write_text(r.text, encoding="utf-8")
        return list(csv.DictReader(io.StringIO(r.text)))
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        if CACHE_RANKING.exists():
            print(f"[AVISO] ClubElo no respondió tras varios intentos ({e}). "
                  f"Usando el último ranking guardado en caché.")
            return list(csv.DictReader(io.StringIO(CACHE_RANKING.read_text(encoding="utf-8"))))
        print("[AVISO] ClubElo no respondió y no hay caché previo disponible.")
        raise


def obtener_historial_club(nombre_club):
    """
    Devuelve el historial de Elo de un club específico.
    El nombre debe coincidir con la ortografía de ClubElo
    (revisa en obtener_ranking_clubelo si no estás seguro).
    """
    url = f"http://api.clubelo.com/{nombre_club}"
    r = _get_con_reintentos(url, headers=HEADERS)
    reader = csv.DictReader(io.StringIO(r.text))
    return list(reader)


# ---------------------------------------------------------------------------
# 2. ELORATINGS.NET  (selecciones nacionales)
# ---------------------------------------------------------------------------

def obtener_ranking_selecciones():
    """
    Devuelve el ranking Elo mundial de selecciones nacionales.
    Eloratings.net no publica un CSV/JSON oficial y estable, así que
    leemos la tabla de su página principal.
    """
    url = "https://www.eloratings.net/World.tsv"
    r = _get_con_reintentos(url, headers=HEADERS)
    if r.status_code == 200 and "\t" in r.text:
        filas = [l.split("\t") for l in r.text.strip().split("\n")]
        return filas

    # Fallback: si el .tsv cambia de ruta, avisamos claramente en vez
    # de fallar en silencio con datos vacíos.
    raise RuntimeError(
        "No se pudo leer el ranking de selecciones desde eloratings.net. "
        "Es posible que la URL del archivo .tsv haya cambiado. "
        "Abre https://www.eloratings.net en el navegador, busca en el "
        "código fuente (Ctrl+U) la petición que carga la tabla, y actualiza "
        "la variable 'url' en obtener_ranking_selecciones()."
    )


# ---------------------------------------------------------------------------
# 3. FOOTBALL-DATA.CO.UK  (resultados históricos -> goal index de clubes)
# ---------------------------------------------------------------------------

# LIGAS PRINCIPALES: un archivo CSV por temporada, patrón:
#   https://www.football-data.co.uk/mmz4281/{temporada}/{codigo}.csv
LIGAS_FOOTBALL_DATA = {
    # Inglaterra
    "E0": "Premier League", "E1": "Championship", "E2": "League One",
    "E3": "League Two", "EC": "Conference / National League",
    # Escocia
    "SC0": "Scottish Premiership", "SC1": "Scottish Championship",
    "SC2": "Scottish League One", "SC3": "Scottish League Two",
    # Alemania
    "D1": "Bundesliga", "D2": "2. Bundesliga",
    # Italia
    "I1": "Serie A", "I2": "Serie B",
    # España
    "SP1": "La Liga", "SP2": "La Liga 2",
    # Francia
    "F1": "Ligue 1", "F2": "Ligue 2",
    # Otros
    "N1": "Eredivisie (Países Bajos)",
    "B1": "Pro League (Bélgica)",
    "P1": "Primeira Liga (Portugal)",
    "T1": "Süper Lig (Turquía)",
    "G1": "Super League (Grecia)",
}

# LIGAS EXTRA: un solo archivo con TODAS las temporadas, patrón distinto:
#   https://www.football-data.co.uk/new/{codigo}.csv
# (Cubren ligas fuera de Europa occidental que ClubElo también mide.)
LIGAS_FOOTBALL_DATA_EXTRA = {
    "ARG": "Argentina - Primera División",
    "AUT": "Austria - Bundesliga",
    "BRA": "Brasil - Série A",
    "CHN": "China - Super League",
    "DNK": "Dinamarca - Superliga",
    "FIN": "Finlandia - Veikkausliiga",
    "IRL": "Irlanda - Premier Division",
    "JPN": "Japón - J1 League",
    "MEX": "México - Liga MX",
    "NOR": "Noruega - Eliteserien",
    "POL": "Polonia - Ekstraklasa",
    "ROU": "Rumania - Liga I",
    "RUS": "Rusia - Premier League",
    "SWE": "Suecia - Allsvenskan",
    "SWZ": "Suiza - Super League",
    "USA": "Estados Unidos - MLS",
}
# NOTA: si alguno de estos códigos ya no coincide (football-data.co.uk los
# cambia de tanto en tanto), entra a https://www.football-data.co.uk/<pais>.php
# y revisa el enlace real de descarga del CSV para corregir el código aquí.


def obtener_resultados_liga(codigo_liga, temporada="2526"):
    """
    Descarga el CSV de resultados de una liga PRINCIPAL para una temporada.
    codigo_liga: ej. 'E0' (Premier League), 'SP1' (La Liga)
    temporada:   ej. '2526' = temporada 2025/26
    """
    url = f"https://www.football-data.co.uk/mmz4281/{temporada}/{codigo_liga}.csv"
    r = _get_con_reintentos(url, headers=HEADERS)
    reader = csv.DictReader(io.StringIO(r.text))
    return list(reader)


def obtener_resultados_liga_extra(codigo_liga):
    """
    Descarga el CSV de una liga EXTRA (todas las temporadas en un solo
    archivo). Filtra internamente para devolver solo los partidos más
    recientes (última temporada disponible en el archivo), para que el
    Goal Index refleje la forma actual de los equipos y no un promedio de
    20 años.
    """
    url = f"https://www.football-data.co.uk/new/{codigo_liga}.csv"
    r = _get_con_reintentos(url, headers=HEADERS)
    r.raise_for_status()
    reader = csv.DictReader(io.StringIO(r.text))
    filas = list(reader)

    # Las ligas extra suelen traer una columna 'Season' (ej. '2025/2026').
    # Nos quedamos solo con la temporada más reciente presente en el archivo.
    if filas and "Season" in filas[0]:
        temporada_reciente = sorted({f["Season"] for f in filas if f.get("Season")})[-1]
        filas = [f for f in filas if f.get("Season") == temporada_reciente]

    return filas


def calcular_goal_index(resultados, ultimos_n=None):
    """
    A partir de una lista de partidos jugados (con columnas HomeTeam,
    AwayTeam, FTHG, FTAG, Date de football-data.co.uk), calcula para cada
    equipo:
      - goles_favor_prom: promedio de goles anotados por partido
      - goles_contra_prom: promedio de goles recibidos por partido
      - goal_index: goles_favor_prom - goles_contra_prom

    Si 'ultimos_n' se especifica (ej. 6), solo usa los N partidos MÁS
    RECIENTES de cada equipo (según la columna Date), para calcular la
    "forma reciente" en vez del promedio de toda la temporada.
    """
    partidos_por_equipo = {}

    def _agregar(equipo, fecha, gf, gc):
        partidos_por_equipo.setdefault(equipo, []).append((fecha, gf, gc))

    for partido in resultados:
        home, away = partido.get("HomeTeam"), partido.get("AwayTeam")
        if not home or not away:
            continue
        try:
            gh, ga = int(partido["FTHG"]), int(partido["FTAG"])
        except (KeyError, ValueError):
            continue

        fecha = _parsear_fecha_football_data(partido.get("Date", ""))
        _agregar(home, fecha, gh, ga)
        _agregar(away, fecha, ga, gh)

    resultado = {}
    for equipo, partidos in partidos_por_equipo.items():
        partidos.sort(key=lambda x: x[0], reverse=True)  # más reciente primero
        if ultimos_n:
            partidos = partidos[:ultimos_n]
        if not partidos:
            continue

        gf_prom = sum(p[1] for p in partidos) / len(partidos)
        gc_prom = sum(p[2] for p in partidos) / len(partidos)
        resultado[equipo] = {
            "partidos_jugados": len(partidos),
            "goles_favor_prom": round(gf_prom, 2),
            "goles_contra_prom": round(gc_prom, 2),
            "goal_index": round(gf_prom - gc_prom, 2),
        }
    return resultado


def _parsear_fecha_football_data(texto_fecha):
    """football-data.co.uk usa DD/MM/YY o DD/MM/YYYY. Si no se puede
    parsear, devuelve una fecha muy antigua (para que quede al final al
    ordenar de más reciente a más antigua)."""
    import datetime as _dt
    for formato in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return _dt.datetime.strptime(texto_fecha, formato)
        except (ValueError, TypeError):
            continue
    return _dt.datetime(1900, 1, 1)


def _calcular_goal_index_viejo_no_usar(resultados):
    pass  # eliminado, ya no se usa


# ---------------------------------------------------------------------------
# 4. MATCHING DE NOMBRES (los nombres de equipo casi nunca coinciden 100%
#    entre ClubElo, eloratings.net y football-data.co.uk)
# ---------------------------------------------------------------------------

def buscar_equipo_similar(nombre, lista_nombres, n=3, corte=0.5):
    """
    Devuelve las 'n' coincidencias más parecidas a 'nombre' dentro de
    'lista_nombres'. Útil para mapear 'Man United' <-> 'Manchester United'
    <-> 'Man Utd' entre las distintas fuentes.
    """
    return difflib.get_close_matches(nombre, lista_nombres, n=n, cutoff=corte)


# ---------------------------------------------------------------------------
# 5. API-FOOTBALL (api-sports.io)  -> SOLO para la vigilancia en vivo
#    Plan gratis = 100 peticiones/día. Cada función de abajo está pensada
#    para consumir la menor cantidad de peticiones posible.
# ---------------------------------------------------------------------------

def obtener_fixtures_por_fecha(fecha_iso):
    """
    1 petición: todos los partidos programados en el mundo para 'fecha_iso'
    (formato YYYY-MM-DD).
    """
    return _api_football_request("fixtures", params={"date": fecha_iso})


def obtener_partidos_en_vivo():
    """
    1 petición: TODOS los partidos que están en vivo en este momento,
    en el mundo. Independiente de cuántos partidos estés vigilando,
    esto siempre cuesta 1 sola petición contra el cupo del día.
    """
    return _api_football_request("fixtures", params={"live": "all"})


def obtener_estadisticas_fixture(fixture_id):
    """
    1 petición POR partido.
    Devuelve una lista con las estadísticas de ambos equipos
    (tiros, córners, posesión, etc.).
    """
    return _api_football_request("fixtures/statistics", params={"fixture": fixture_id})


# --- Goal Index para ligas que ClubElo mide pero football-data.co.uk NO cubre ---
# Se usa 1 vez por semana (no todos los días), para no competir por cupo con
# la vigilancia en vivo. Ver LIGAS_API_FOOTBALL_EXTRA más abajo: hay que
# llenarla a mano con los league_id de API-Football (usa
# buscar_id_liga_api_football() una sola vez para encontrarlos).

# Ejemplo (llénalo con las ligas que te interesen; deja {} si no quieres usar esto):
#   LIGAS_API_FOOTBALL_EXTRA = {
#       239: "Colombia - Categoría Primera A",
#       242: "Ecuador - Liga Pro",
#       281: "Perú - Liga 1",
#       128: "Argentina - Copa Libertadores",  # ejemplo, verifica el id real
#   }
LIGAS_API_FOOTBALL_EXTRA = {}

TEMPORADA_API_FOOTBALL = 2026  # año de inicio de la temporada actual


def buscar_id_liga_api_football(nombre_busqueda):
    """
    Ayuda a encontrar el league_id correcto en API-Football. Se usa UNA
    SOLA VEZ al configurar (no en las corridas automáticas).
    Ejemplo: buscar_id_liga_api_football("Ecuador")
    """
    resultados = _api_football_request("leagues", params={"search": nombre_busqueda})
    return [
        {"id": x["league"]["id"], "nombre": x["league"]["name"], "pais": x["country"]["name"]}
        for x in resultados
    ]


def obtener_standings_liga(league_id, temporada=TEMPORADA_API_FOOTBALL):
    """
    1 petición: tabla de posiciones completa de una liga, con goles a favor
    y en contra de CADA equipo ya calculados.
    """
    respuesta = _api_football_request("standings", params={"league": league_id, "season": temporada})
    if not respuesta:
        return []
    grupos = respuesta[0]["league"]["standings"]
    return [equipo for grupo in grupos for equipo in grupo]


def calcular_goal_index_desde_standings(standings):
    """
    Convierte la tabla de posiciones de API-Football en el mismo formato
    que calcular_goal_index() (goles_favor_prom, goles_contra_prom,
    goal_index), para poder mezclarlo con los datos de football-data.co.uk.
    """
    resultado = {}
    for equipo in standings:
        jugados = equipo["all"]["played"]
        if not jugados:
            continue
        gf_prom = equipo["all"]["goals"]["for"] / jugados
        gc_prom = equipo["all"]["goals"]["against"] / jugados
        resultado[equipo["team"]["name"]] = {
            "partidos_jugados": jugados,
            "goles_favor_prom": round(gf_prom, 2),
            "goles_contra_prom": round(gc_prom, 2),
            "goal_index": round(gf_prom - gc_prom, 2),
        }
    return resultado


def obtener_resultado_fixture(fixture_id):
    """
    1 petición: consulta un partido específico por su fixture_id y
    devuelve su estado actual (si ya terminó, el marcador final).
    """
    respuesta = _api_football_request("fixtures", params={"id": fixture_id})
    return respuesta[0] if respuesta else None


def obtener_prediccion_fixture(fixture_id):
    """
    1 petición POR partido: la predicción propia de API-Football.
    """
    respuesta = _api_football_request("predictions", params={"fixture": fixture_id})
    return respuesta[0] if respuesta else None
