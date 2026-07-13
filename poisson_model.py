"""
poisson_model.py
-----------------
Corrige el hallazgo que hicimos comparando cuotas reales: la fórmula
simple de Elo (solo gana/pierde) ignora el empate y por eso infla la
probabilidad del favorito. Este módulo reparte correctamente la
probabilidad entre victoria/empate/derrota usando goles esperados +
distribución de Poisson — igual que en el proyecto del predictor.

Dos fuentes se combinan para estimar los goles esperados de cada equipo:
  1. La diferencia de Elo (siempre disponible)
  2. El Goal Index del equipo, si lo tenemos (ataque/defensa reciente,
     de football-data.co.uk o del caché de ligas extra)

Si no hay Goal Index disponible para alguno de los dos equipos, el
cálculo sigue funcionando usando SOLO la diferencia de Elo (no se cae a
un 50-50 plano) — así todos los partidos son evaluables, con o sin Goal
Index.

También se usa para recalcular, EN VIVO, la probabilidad de que el
favorito termine ganando dado el marcador actual y los minutos que
quedan — esto reemplaza la necesidad de una "cuota en vivo" real.
"""

import math
from functools import lru_cache

VENTAJA_LOCAL_ELO = 70
PROMEDIO_GOLES_LIGA = 1.35
PESO_ELO_EN_GOLES = 1 / 200  # cada 200 pts de Elo de diferencia ~ 1 gol de ventaja

CUOTA_MAXIMA_FAVORITO = 1.67  # equivalente a probabilidad >= 60%
PROB_MINIMA_FAVORITO = 0.60


def cumple_filtro_cuota(evaluacion):
    """True si el favorito cumple el filtro de probabilidad inicial >= 60%."""
    return evaluacion["probabilidad"] >= PROB_MINIMA_FAVORITO


def probabilidad_gol_inminente(lambda_equipo_total, tiros_puerta_recientes, minutos_ventana=15,
                                minutos_partido=90):
    """
    Probabilidad de que UN equipo (cualquiera, favorito o no) anote en los
    próximos `minutos_ventana` minutos.

    Combina dos señales SUMADAS (no una multiplicando a la otra):
      1. Su tasa esperada de goles pre-partido (Elo+GoalIndex), escalada
         a la ventana de minutos.
      2. Los tiros a puerta que generó en la revisión más reciente,
         convertidos a goles esperados con una tasa de conversión típica
         del fútbol (~11% de los tiros a puerta terminan en gol).

    Sumar en vez de multiplicar es importante para equipos con Elo bajo:
    si un equipo débil está teniendo una racha de tiros a puerta ahora
    mismo, esa señal cuenta con fuerza propia — no queda opacada por su
    baja tasa esperada de toda la temporada. Esta tasa de conversión es
    un punto de partida razonable, no un dato calibrado con tus propios
    datos todavía; se puede ajustar más adelante con el historial real
    de alertas.
    """
    TASA_CONVERSION_TIRO_A_PUERTA = 0.11

    lambda_por_minuto_base = lambda_equipo_total / minutos_partido
    lambda_base_ventana = lambda_por_minuto_base * minutos_ventana

    lambda_presion = tiros_puerta_recientes * TASA_CONVERSION_TIRO_A_PUERTA

    lambda_total = lambda_base_ventana + lambda_presion
    return 1 - math.exp(-lambda_total)


def goles_esperados(elo_local, elo_visitante, goal_index_local=None, goal_index_visitante=None,
                     ventaja_local=VENTAJA_LOCAL_ELO, promedio_liga=PROMEDIO_GOLES_LIGA):
    """
    Devuelve (lambda_local, lambda_visitante): los goles esperados de
    cada equipo en ESTE partido, combinando Elo (siempre) y Goal Index
    (si está disponible).
    """
    diff_elo = (elo_local + ventaja_local) - elo_visitante
    ajuste_elo = diff_elo * PESO_ELO_EN_GOLES

    gi_local = goal_index_local or 0
    gi_visitante = goal_index_visitante or 0

    lambda_local = max(0.15, promedio_liga + ajuste_elo / 2 + gi_local / 2 - gi_visitante / 4)
    lambda_visitante = max(0.15, promedio_liga - ajuste_elo / 2 + gi_visitante / 2 - gi_local / 4)
    return lambda_local, lambda_visitante


@lru_cache(maxsize=None)
def _poisson_pmf(k, lam):
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def matriz_marcadores(lambda_local, lambda_visitante, max_goles=6):
    matriz = {}
    for gl in range(max_goles + 1):
        for gv in range(max_goles + 1):
            matriz[(gl, gv)] = _poisson_pmf(gl, round(lambda_local, 4)) * _poisson_pmf(gv, round(lambda_visitante, 4))
    return matriz


def probabilidades_1x2(matriz):
    p_local = sum(p for (gl, gv), p in matriz.items() if gl > gv)
    p_empate = sum(p for (gl, gv), p in matriz.items() if gl == gv)
    p_visitante = sum(p for (gl, gv), p in matriz.items() if gl < gv)
    return p_local, p_empate, p_visitante


def evaluar_favorito(elo_local, elo_visitante, goal_index_local=None, goal_index_visitante=None):
    """
    Reemplaza a la fórmula binaria de Elo. Devuelve quién es favorito,
    su probabilidad real (con empate incluido) y la cuota equivalente,
    más los goles esperados (necesarios luego para el recálculo en vivo).
    """
    lam_local, lam_visitante = goles_esperados(elo_local, elo_visitante, goal_index_local, goal_index_visitante)
    matriz = matriz_marcadores(lam_local, lam_visitante)
    p_local, p_empate, p_visitante = probabilidades_1x2(matriz)

    if p_local >= p_visitante:
        lado, prob = "local", p_local
    else:
        lado, prob = "visitante", p_visitante

    return {
        "lado": lado,
        "probabilidad": prob,
        "cuota_inicial": round(1 / prob, 2) if prob > 0 else None,
        "lambda_local": round(lam_local, 3),
        "lambda_visitante": round(lam_visitante, 3),
    }


def probabilidad_favorito_en_vivo(lambda_local, lambda_visitante, goles_local_actual, goles_visitante_actual,
                                   minuto_actual, favorito_es_local, minutos_partido=90):
    """
    LA PIEZA NUEVA: dado el marcador actual y el minuto, recalcula con
    Poisson la probabilidad de que el favorito termine ganando el
    partido. Escala los goles esperados originales según los minutos que
    quedan, y sólo simula los goles RESTANTES.

    Esto es matemáticamente equivalente a lo que pediste originalmente
    con "la cuota subió": si esta probabilidad cae mucho respecto a la
    inicial, es la misma señal, sin necesitar cuotas reales.
    """
    minutos_restantes = max(0, minutos_partido - minuto_actual)
    fraccion = minutos_restantes / minutos_partido

    lam_local_restante = lambda_local * fraccion
    lam_visitante_restante = lambda_visitante * fraccion

    matriz_restante = matriz_marcadores(lam_local_restante, lam_visitante_restante, max_goles=6)

    prob_favorito_gana = 0.0
    for (gl_restante, gv_restante), p in matriz_restante.items():
        gl_final = goles_local_actual + gl_restante
        gv_final = goles_visitante_actual + gv_restante
        if favorito_es_local:
            gana_favorito = gl_final > gv_final
        else:
            gana_favorito = gv_final > gl_final
        if gana_favorito:
            prob_favorito_gana += p

    return prob_favorito_gana
