"""
telegram_utils.py
------------------
Envío de mensajes a Telegram usando un bot propio (gratis).

Cómo crear tu bot (una sola vez):
  1. En Telegram, habla con @BotFather -> /newbot -> sigue los pasos.
     Te da un TOKEN (algo como 123456789:ABCdefGhIJK...).
  2. Escríbele cualquier mensaje a TU bot (para que pueda hablarte).
  3. Abre en el navegador:
     https://api.telegram.org/bot<TU_TOKEN>/getUpdates
     y busca el campo "chat":{"id": ...}  -> ese número es tu CHAT_ID.
  4. Guarda ambos como "Secrets" en tu repositorio de GitHub:
     Settings -> Secrets and variables -> Actions -> New repository secret
       TELEGRAM_BOT_TOKEN = el token
       TELEGRAM_CHAT_ID   = tu chat id
"""

import os
import requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def escapar_html(texto):
    """
    Convierte &, < y > a su forma segura para HTML. Telegram usa
    parse_mode=HTML, así que cualquier texto dinámico que insertemos en
    un mensaje (nombres de equipo, ligas, etc.) DEBE pasar por aquí antes
    de meterlo al mensaje — si no, un nombre de equipo con "&" (bastante
    común, ej. clubes con "&" en el nombre oficial) rompe el envío entero
    con un error 400 de Telegram. Ya nos pasó una vez con el símbolo
    "<=" en el texto fijo del mensaje; esto lo generaliza para CUALQUIER
    texto que venga de datos externos (nombres de equipo), no solo para
    los símbolos que ya conocemos.

    IMPORTANTE: solo se aplica al texto dinámico (nombres, etc.), NUNCA
    a las etiquetas <b>...</b> que nosotros mismos escribimos a propósito
    en el mensaje — esas deben quedar intactas para que Telegram las
    interprete como negrita.
    """
    if texto is None:
        return ""
    return str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def enviar_mensaje_telegram(texto):
    """Envía 'texto' al chat configurado. No lanza error si faltan credenciales,
    solo avisa por consola (para no tumbar el workflow completo)."""
    if not TOKEN or not CHAT_ID:
        print("[AVISO] Falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID. No se envió el mensaje:")
        print(texto)
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": texto, "parse_mode": "HTML"}, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[ERROR] No se pudo enviar el mensaje de Telegram: {e}")
        return False
