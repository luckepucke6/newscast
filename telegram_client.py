"""Telegram notifications: audio, messages, error alerts, and cost alerts."""
import logging
import os

import requests

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_audio(path: str, episode: int, today_str: str, n: int, cfg: dict) -> None:
    """Skickar ett MP3-avsnitt till Telegram."""
    ep_cfg = cfg["episodes"][f"ep{episode}"]
    label = ep_cfg["label"]
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendAudio"
    with open(path, "rb") as f:
        resp = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": f"🎙 Avsnitt {episode}: {label}\n{today_str} · {n} nyheter",
                "performer": label,
                "title": f"Avsnitt {episode} – {today_str}",
            },
            files={"audio": (f"avsnitt{episode}.mp3", f, "audio/mpeg")},
            timeout=120,
        )
    if not resp.ok:
        raise RuntimeError(f"Telegram-fel {resp.status_code}: {resp.text}")
    logger.info("Avsnitt %d skickat till Telegram!", episode)


def send_message(text: str) -> None:
    """Skickar ett textmeddelande till Telegram."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": text[:4096]},
            timeout=10,
        )
    except Exception as e:
        logger.warning("send_message misslyckades: %s", e)


def notify_error(message: str) -> None:
    """Skickar ett felmeddelande till Telegram."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"⚠️ Nyhetspodd kraschade:\n\n{message[:1000]}",
            },
            timeout=10,
        )
    except Exception:
        pass


def notify_cost(cost_sek: float, cost_usd: float, summary: str) -> None:
    """Skickar en kostnadsvarning till Telegram om tröskeln överstigs."""
    text = (
        f"💸 Kostnadslarm! {cost_sek:.2f} SEK ({cost_usd:.4f} USD) denna körning.\n\n{summary}"
    )
    send_message(text)
