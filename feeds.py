"""Article fetching from RSS feeds and weather API."""
import logging
from datetime import datetime

import feedparser
import requests

from memory import article_key

logger = logging.getLogger(__name__)

WMO_CODES = {
    0: "klart", 1: "mestadels klart", 2: "delvis molnigt", 3: "mulet",
    45: "dimmigt", 48: "isbildande dimma",
    51: "lätt duggregn", 53: "duggregn", 55: "kraftigt duggregn",
    61: "lätt regn", 63: "regn", 65: "kraftigt regn",
    71: "lätt snöfall", 73: "snöfall", 75: "kraftigt snöfall",
    80: "lätta regnskurar", 81: "regnskurar", 82: "kraftiga regnskurar",
    95: "åskväder", 99: "åskväder med hagel",
}


def fetch_articles(feeds: dict, history: dict, max_per_feed: int = 4) -> list:
    articles = []
    now_iso = datetime.now().isoformat()
    skipped = 0

    for category, url in feeds.items():
        feed = feedparser.parse(url)
        count = 0
        for entry in feed.entries:
            if count >= max_per_feed:
                break
            title = entry.title
            link = entry.get("link", "")
            summary = (
                entry.get("summary", "")[:500]
                .replace("<b>", "").replace("</b>", "")
            )
            key = article_key(title, link)
            if key in history:
                skipped += 1
                continue
            articles.append({
                "category": category,
                "title": title,
                "url": link,
                "summary": summary,
            })
            history[key] = now_iso
            count += 1

    logger.info("%d nya artiklar (%d redan sedda)", len(articles), skipped)
    return articles


def fetch_weather() -> str:
    """Hämtar aktuellt väder för Stockholm via Open-Meteo (gratis, ingen API-nyckel)."""
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": 59.33, "longitude": 18.07,
                "current": "temperature_2m,weathercode",
                "timezone": "Europe/Stockholm",
            },
            timeout=10,
        )
        data = resp.json()["current"]
        temp = round(data["temperature_2m"])
        code = data["weathercode"]
        desc = WMO_CODES.get(code, "växlande väder")
        weather = f"{temp} grader och {desc} i Stockholm"
        logger.info("Väder: %s", weather)
        return weather
    except Exception as e:
        logger.warning("Väder ej tillgängligt: %s", e)
        return ""
