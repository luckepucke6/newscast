"""Persistence: URL history and topic memory."""
import json
import logging
import os
import hashlib
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def load_history(cfg: dict) -> dict:
    path = cfg["history"]["file"]
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def save_history(history: dict, cfg: dict) -> None:
    days = cfg["history"]["days"]
    path = cfg["history"]["file"]
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    pruned = {k: v for k, v in history.items() if v >= cutoff}
    with open(path, "w") as f:
        json.dump(pruned, f, indent=2)
    logger.info("Historik: %d poster sparade", len(pruned))


def load_memory(cfg: dict) -> list:
    path = cfg["history"]["memory_file"]
    days = cfg["history"]["days"]
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            entries = json.load(f)
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        return [e for e in entries if e.get("date", "") >= cutoff]
    except Exception:
        return []


def save_memory(memory: list, new_entry: dict, cfg: dict) -> None:
    path = cfg["history"]["memory_file"]
    days = cfg["history"]["days"]
    memory.append(new_entry)
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    pruned = [e for e in memory if e.get("date", "") >= cutoff]
    with open(path, "w") as f:
        json.dump(pruned, f, ensure_ascii=False, indent=2)


def memory_to_context(memory: list, episode: int) -> str:
    relevant = [e for e in memory if e.get("episode") == episode]
    if not relevant:
        return ""
    lines = []
    for entry in relevant[-5:]:
        lines.append(f"\n{entry['date'][:10]}:")
        for h in entry.get("headlines", []):
            lines.append(f"  - {h}")
    return "\n".join(lines)


def extract_headlines(script: str, articles: list) -> list:
    return [f"[{a['category']}] {a['title'][:80]}" for a in articles[:8]]


def article_key(title: str, url: str) -> str:
    return hashlib.md5((title + url).lower().encode()).hexdigest()
