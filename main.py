#!/usr/bin/env python3
"""
Daily News Podcast — main entry point.
Avsnitt 1: Världsnyheter & Sverige  — varje dag
Avsnitt 2: AI & Teknik              — mån, ons, fre

Modules: memory, feeds, script, tts, telegram_client, costs, dedup
Config:  config.yaml
"""

import json
import logging
import os
import traceback
from datetime import datetime

import anthropic
import yaml

from costs import CostTracker
from dedup import cluster_deduplicate
from feeds import fetch_articles, fetch_weather
from memory import (
    extract_headlines,
    load_history,
    load_memory,
    memory_to_context,
    save_history,
    save_memory,
)
from script import (
    NEXT_TECH_DAY,
    SWEDISH_DAYS,
    TECH_DAYS,
    _dynamic_length_params,
    extend_script,
    filter_by_relevance,
    judge_script,
    swedish_date,
    write_script,
)
from telegram_client import notify_cost, notify_error, send_audio
from tts import text_to_speech

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

COSTS_FILE = "costs.json"
MAX_COSTS_ENTRIES = 30


def _load_config() -> dict:
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def _append_cost_entry(entry: dict) -> None:
    data = []
    if os.path.exists(COSTS_FILE):
        try:
            with open(COSTS_FILE) as f:
                data = json.load(f)
        except Exception:
            data = []
    data.append(entry)
    data = data[-MAX_COSTS_ENTRIES:]
    with open(COSTS_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generate_episode(
    episode: int,
    feeds: dict,
    history: dict,
    today_str: str,
    weekday: int,
    cfg: dict,
    claude_client,
    cost_tracker: CostTracker,
    weather: str = "",
    used_titles: set = None,
    memory: list = None,
) -> set:
    """Genererar ett avsnitt och returnerar set med använda titlar."""
    ep_cfg = cfg["episodes"][f"ep{episode}"]
    label = ep_cfg["label"]
    logger.info("── Avsnitt %d: %s ──", episode, label)

    max_per_feed = ep_cfg["articles_per_feed"]
    articles = fetch_articles(feeds, history, max_per_feed=max_per_feed)

    # Koordinering: filtrera bort artiklar EP1 redan använt
    if used_titles:
        before = len(articles)
        articles = [a for a in articles if a["title"] not in used_titles]
        logger.info("Koordinering: %d artiklar överlappade med avsnitt 1", before - len(articles))

    if not articles:
        logger.warning("Inga nya artiklar. Hoppar över avsnitt %d.", episode)
        return used_titles or set()

    logger.info("Deduplicerar artiklar...")
    articles = cluster_deduplicate(articles, cfg)

    # Relevansfilter bara för EP1
    if episode == 1:
        logger.info("Filtrerar på relevans...")
        articles = filter_by_relevance(articles, cfg, claude_client, cost_tracker)

    logger.info("Skriver manus...")
    memory_context = memory_to_context(memory, episode) if memory else ""
    script = write_script(
        episode, articles, today_str, weekday, cfg, claude_client,
        weather, cost_tracker, memory_context=memory_context,
    )

    ep_min, ep_max, _ = _dynamic_length_params(
        len(articles), ep_cfg["min_words"], ep_cfg["max_words"]
    )
    max_extend = 3
    for attempt in range(1, max_extend + 1):
        if len(script.split()) >= ep_min:
            break
        logger.info("För kort (%d ord) — bygger ut (försök %d/%d)...", len(script.split()), attempt, max_extend)
        script = extend_script(script, episode, ep_min, cfg, claude_client, cost_tracker)

    logger.info("Granskar manus...")
    approved, verdict = judge_script(episode, script, cfg, claude_client, cost_tracker)
    if not approved:
        logger.warning("Skickar ändå — %s", verdict)

    audio_path = text_to_speech(script, episode, cfg)
    n = len(articles)
    send_audio(audio_path, episode, today_str, n, cfg)

    if memory is not None:
        save_memory(memory, {
            "date": datetime.now().isoformat(),
            "episode": episode,
            "headlines": extract_headlines(script, articles),
        }, cfg)

    return {a["title"] for a in articles}


def main():
    cfg = _load_config()

    claude_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    cost_tracker = CostTracker.from_config(cfg)

    now = datetime.now()
    weekday = now.weekday()
    today_str = swedish_date(now)
    force_ep2 = os.environ.get("FORCE_EPISODE2", "").lower() == "true"

    logger.info("📰 Nyhetspodd — %s", today_str)

    history = load_history(cfg)
    memory = load_memory(cfg)
    weather = fetch_weather()

    feeds_ep1 = cfg["feeds"]["ep1"]
    feeds_ep2 = cfg["feeds"]["ep2"]
    tech_days = set(cfg.get("tech_days", [0, 2, 4]))

    # EP1 — kör alltid
    used_titles = generate_episode(
        1, feeds_ep1, history, today_str, weekday,
        cfg, claude_client, cost_tracker, weather,
        memory=memory,
    )

    # EP2 — mån/ons/fre
    if weekday in tech_days or force_ep2:
        if force_ep2 and weekday not in tech_days:
            logger.info("(FORCE_EPISODE2 aktiv — kör avsnitt 2 trots %s)", SWEDISH_DAYS[weekday])
        generate_episode(
            2, feeds_ep2, history, today_str, weekday,
            cfg, claude_client, cost_tracker,
            used_titles=used_titles,
            memory=memory,
        )
    else:
        logger.info("Avsnitt 2 hoppas över idag (%s) — sänds mån/ons/fre.", SWEDISH_DAYS[weekday])

    logger.info("Sparar historik...")
    save_history(history, cfg)

    logger.info(cost_tracker.summary())

    # Spara kostnadsdata
    _append_cost_entry({
        "date": now.isoformat(),
        "usd": cost_tracker.total_usd(),
        "sek": cost_tracker.total_sek(),
        "claude_input": cost_tracker.claude_input_tokens,
        "claude_output": cost_tracker.claude_output_tokens,
    })

    # Kostnadsvarning om tröskeln överstigs
    threshold = cfg.get("costs", {}).get("alert_threshold_sek", 10.0)
    if cost_tracker.total_sek() > threshold:
        notify_cost(cost_tracker.total_sek(), cost_tracker.total_usd(), cost_tracker.summary())

    logger.info("✅ Klart — %s", today_str)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        error_msg = traceback.format_exc()
        logger.error("💥 Fel:\n%s", error_msg)
        notify_error(error_msg)
        raise
