# Alertas de gol en vivo (seguimiento del mayor número de partidos posible)

Sistema automático que detecta partidos con un favorito claro (probabilidad
inicial ≥60% vía Elo + Goal Index), los vigila en vivo, y avisa por
Telegram con distintos tipos de alerta según cuán probable es que se
anote un gol pronto. Corre solo, gratis, en GitHub Actions.

## Cómo llegamos hasta acá

Este proyecto empezó con un objetivo distinto (detectar valor de apuesta
en favoritos de cuota ≤1.35 con cuotas reales). Después de comprobar que
no existe una fuente de cuotas reales gratis y accesible desde tu país,
y de una sesión larga de lluvia de ideas, el objetivo cambió a:
**seguimiento del mayor número de partidos posible, con alertas de
probabilidad de gol**. El diseño de abajo es el resultado final.

## Las 5 fases

| Fase | Cuándo | Qué hace |
|---|---|---|
| 1. Selección | Desde las 04:00, reintenta cada 5 min hasta lograrlo | Filtra partidos con favorito de probabilidad inicial ≥60% |
| 2. Resumen | 07:00 | Manda a Telegram la lista de partidos de hoy |
| 3. Vigilancia | Cada 5-15 min (adaptativo), solo en ventanas de partidos en curso | Calcula probabilidad de gol y manda la alerta que aplique |
| 4. Cierre | 23:30 | Cierra resultados, archiva el día, actualiza el Excel |
| Reporte diario | 06:00 (día siguiente) | Resultados de ayer (✅/❌) + cupo de API-Football usado |

## Los 7 tipos de alerta

| Situación | Alerta |
|---|---|
| Favorito perdiendo por 1 + favorito genera peligro | 🟠 Posible empate |
| Empatando + favorito con la iniciativa | 🟢 Posible victoria del favorito |
| Empatando + rival con la iniciativa | 🔴 Posible gol del no favorito |
| 0-0, antes del min 30, favorito atacando mucho | ⏱️ Gana favorito 1er tiempo (más específica que la anterior) |
| Favorito ganando + rival presiona | ⚠️ Cuidado, rival presionando |
| Favorito ganando + favorito sigue dominando | 🔵 Posible ampliación de marcador |
| Minuto 75-85, empatado o -1, dominó ≥75% del partido | ⏰ Posible gol de cierre |

Cuando dos o más aplican al mismo tiempo, se manda la de **mayor
probabilidad de gol calculada** (empate técnico se resuelve por
especificidad). **Sin límite de alertas por partido** — un mismo partido
puede recibir varias a lo largo de los 90 minutos, para tener un
seguimiento tipo relato en vivo.

Cada alerta incluye estadísticas completas (tiros, tiros a puerta,
córners, posesión) y links de búsqueda a BeSoccer y Ecuabet (vía Google
— no son URLs exactas, ninguno tiene API pública gratis).

## Corrección importante: GitHub Actions no es confiable con crons frecuentes

Se detectó (con datos reales de un día de prueba) que GitHub Actions **no
garantiza** que un workflow programado cada 5 minutos corra realmente cada
5 minutos — puede tardar hasta una hora entre ejecuciones, o saltarse
ejecuciones por completo. Es una limitación documentada de la plataforma,
no un bug del código. Esto causaba que Fase 3 casi no vigilara los
partidos, y que Fase 4 (un solo disparo a las 23:30) a veces no llegara a
correr ese día.

**La solución aplicada:**
- **Fase 3** ahora se dispara solo 4 veces al día (mucho más confiable) y
  cada disparo se queda corriendo por dentro ~5.5 horas, revisando cada 5
  minutos con una espera propia (`sleep`) que no depende de que GitHub lo
  vuelva a agendar.
- **Fase 2, Fase 4, y el Reporte diario** pasaron de "un solo disparo a
  hora fija" a "reintentar cada 15 min dentro de una ventana de 1-2
  horas", con un mecanismo (`estado_diario.py`) que evita que se repita
  el mensaje una vez que ya se envió ese día.
- Todos los `git push` ahora reintentan automáticamente con
  `git pull --rebase` si chocan con otra ejecución escribiendo al mismo
  tiempo.

## Decisiones importantes de esta versión

- **"Cuota inicial" sigue siendo un proxy de Elo+GoalIndex**, no una
  cuota real de casa de apuestas.
- **Se investigó tener 2+ cuentas de API-Football para duplicar el
  cupo, pero se descartó**: sus términos de servicio prohíben
  explícitamente múltiples cuentas para eludir el límite gratuito.
- **La frecuencia adaptativa (10 min si hay ≤5 partidos en ventana, 15
  min si hay más) es la herramienta principal para estirar el cupo**,
  ya que ahora se piden estadísticas para TODOS los partidos en
  ventana, no solo los que van empatando/-1 como antes.
- **El umbral de "probabilidad de gol inminente" quedó en 35% por
  defecto** (`UMBRAL_GOL_INMINENTE` en `monitor.py`) — nunca se
  confirmó explícitamente, ajústalo ahí si quieres más o menos alertas.
- **Forma reciente (últimos 6 partidos) mezclada 60%/40% con
  temporada completa**, solo para equipos de las 38 ligas de
  football-data.co.uk (gratis). Fuera de esas ligas, solo Elo.

## Cómo ponerlo en línea

### 1. Crear el repositorio
1. `https://github.com/new` → nombre sugerido `alertas-apuestas` → **Public** → Create

### 2. Subir los archivos (con git, más confiable que arrastrar)
```bash
cd alertas-apuestas
git init
git add .
git commit -m "Version con alertas de gol"
git branch -M main
git remote add origin https://github.com/TU-USUARIO/alertas-apuestas.git
git push -u origin main
```
Si vienes de una versión anterior, borra antes: `probabilidad.py`,
`data/historial_alertas.csv`, `data/partidos_hoy.json`.

### 3. Permisos de escritura
`.../settings/actions` → "Workflow permissions" → **Read and write permissions** → Save

### 4. Credenciales (Secrets)
Puedes reutilizar el mismo bot de Telegram y cuenta de API-Football de
otros proyectos.

`.../settings/secrets/actions` → crea 3:

| Name | Valor |
|---|---|
| `API_FOOTBALL_KEY` | tu API key de https://dashboard.api-football.com |
| `TELEGRAM_BOT_TOKEN` | el token de tu bot (de @BotFather) |
| `TELEGRAM_CHAT_ID` | tu chat id |

### 5. Probar manualmente
`.../actions` → "Fase 1 - Seleccion de partidos" → Run workflow → revisa
que salga ✅ → luego "Fase 2 - Resumen diario" → debería llegarte el
mensaje a Telegram. Fase 3 y el Reporte diario se prueban mejor con
partidos reales en curso / al día siguiente.

## Estructura de archivos

```
fetch_data.py           -> ClubElo, football-data.co.uk, API-Football (reintentos + caché)
poisson_model.py        -> Elo+GoalIndex -> probabilidad realista, probabilidad de gol inminente
goal_index.py            -> Goal Index mezclado (forma reciente 60% + temporada 40%)
cuota_api_football.py    -> contador de uso diario de API-Football
seleccionar_partidos.py -> Fase 1
resumen.py               -> Fase 2
monitor.py               -> Fase 3 (motor de los 7 tipos de alerta)
cerrar_resultados.py     -> Fase 4 (archiva el día + actualiza Excel)
reporte_diario.py        -> Reporte de las 6am
telegram_utils.py        -> envío de mensajes
data/partidos_hoy.json   -> selección + "memoria" del partido (historial_snapshots)
data/historial_dias/     -> un archivo JSON por día, con resultados y uso de API
data/estadisticas.xlsx   -> 2 pestañas: resultados por partido, resumen por día
```

## Limitaciones que debes saber

- **Cupo de API-Football (100/día, una sola cuenta):** con más partidos
  vigilados y estadísticas pedidas para todos, el consumo es mayor que
  en la versión anterior. La frecuencia adaptativa ayuda, pero en un
  día con muchísimos partidos simultáneos podrías acercarte al límite —
  el reporte de las 6am te avisa cuánto quedó disponible.
- **La "probabilidad de gol inminente" es un punto de partida
  razonable, no un modelo calibrado todavía.** La tasa de conversión de
  tiros a puerta (11%) y el umbral de alerta (35%) son valores
  iniciales — el Excel que se va llenando es justamente para poder
  ajustarlos con evidencia real más adelante.
- **BeSoccer y Ecuabet:** links de búsqueda de Google, no URLs exactas.
- **ClubElo** tiene reintentos y caché de respaldo por si el sitio se
  sobrecarga (le pasa de vez en cuando, es un sitio pequeño).
