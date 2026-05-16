#!/usr/bin/env python3
"""
Daily News Podcast
Hämtar nyheter → skriver manus med OpenAI → omvandlar till ljud → skickar via Telegram
"""

import os
import feedparser
import requests
from openai import OpenAI
from datetime import datetime

# ── Klienter & inställningar ─────────────────────────────────────────────────

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Google News RSS-flöden (hämtar svenska + engelska nyheter)
FEEDS = {
    "Tech & AI": (
        "https://news.google.com/rss/search"
        "?q=artificial+intelligence+tech+2024&hl=en&gl=US&ceid=US:en"
    ),
    "Världsnyheter": (
        "https://news.google.com/rss/search"
        "?q=world+news+today&hl=en&gl=US&ceid=US:en"
    ),
    "Politik": (
        "https://news.google.com/rss/search"
        "?q=politics+world+today&hl=en&gl=US&ceid=US:en"
    ),
    "Sverige": (
        "https://news.google.com/rss/search"
        "?q=Sverige+Swedish+news&hl=sv&gl=SE&ceid=SE:sv"
    ),
}

ARTICLES_PER_FEED = 2   # 2 artiklar per kategori = 8 totalt, GPT väljer de 5–7 bästa

SWEDISH_MONTHS = {
    1: "januari", 2: "februari", 3: "mars", 4: "april",
    5: "maj", 6: "juni", 7: "juli", 8: "augusti",
    9: "september", 10: "oktober", 11: "november", 12: "december",
}

# ── Steg 1: Hämta nyheter ────────────────────────────────────────────────────

def fetch_news() -> list[dict]:
    articles = []
    for category, url in FEEDS.items():
        feed = feedparser.parse(url)
        for entry in feed.entries[:ARTICLES_PER_FEED]:
            summary = entry.get("summary", "")
            # Ta bort HTML-taggar från summering
            summary = summary.replace("<b>", "").replace("</b>", "")
            articles.append({
                "category": category,
                "title": entry.title,
                "summary": summary[:400],
            })
    print(f"  Hittade {len(articles)} artiklar")
    return articles

# ── Steg 2: Skriv manus med GPT ─────────────────────────────────────────────

def write_script(articles: list[dict], today_str: str) -> str:
    articles_text = "\n\n".join([
        f"[{a['category']}]\nRubrik: {a['title']}\nIngress: {a['summary']}"
        for a in articles
    ])

    prompt = f"""Du är en personlig nyhetsuppläsare som heter Axel. Du presenterar nyheter som en varm, smart kompis – inte som en formell nyhetsuppläsare.

Skriv ett podcastmanus på SVENSKA för {today_str}. Manuset ska vara 3–5 minuter (ca 450–700 ord).

Välj ut de 5–7 mest intressanta nyheterna nedan och skriv om dem.

Regler:
- Börja med: "God morgon! Jag heter Axel och det här är din dagliga nyhetsuppdatering för {today_str}."
- Förklara svåra begrepp enkelt – som om du förklarar för en smart 12-åring
- Koppla alltid nyheten till hur den faktiskt påverkar vanliga människor i Sverige
- Var konversationell och personlig. Det är okej att ha en liten personlig kommentar.
- Övergångar mellan nyheter ska flöda naturligt, inte kännas som en lista
- Avsluta med: "Det var Axel med din morgonuppdatering – ha en riktigt bra dag!"
- Skriv BARA själva manuset. Inga rubriker, inga noter, inga parenteser.

Dagens nyheter:
{articles_text}"""

    print("  Skriver manus med GPT-4o...")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1200,
        temperature=0.8,
    )
    script = response.choices[0].message.content
    word_count = len(script.split())
    print(f"  Manus klart ({word_count} ord)")
    return script

# ── Steg 3: Omvandla till ljud (TTS) ────────────────────────────────────────

def text_to_speech(script: str) -> str:
    print("  Genererar ljud med OpenAI TTS (Echo)...")
    response = client.audio.speech.create(
        model="tts-1",
        voice="echo",
        input=script,
        speed=1.0,
    )
    audio_path = "/tmp/podcast_today.mp3"
    with open(audio_path, "wb") as f:
        f.write(response.content)
    size_kb = os.path.getsize(audio_path) // 1024
    print(f"  Ljud klart ({size_kb} KB)")
    return audio_path

# ── Steg 4: Skicka till Telegram ─────────────────────────────────────────────

def send_to_telegram(audio_path: str, today_str: str) -> None:
    print("  Skickar till Telegram...")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendAudio"
    with open(audio_path, "rb") as f:
        resp = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": f"🎙️ Din morgonpodd – {today_str}",
                "performer": "Axel",
                "title": f"Nyheter {today_str}",
            },
            files={"audio": ("podcast.mp3", f, "audio/mpeg")},
            timeout=60,
        )
    if resp.ok:
        print("  Skickat till Telegram!")
    else:
        raise RuntimeError(f"Telegram-fel: {resp.status_code} – {resp.text}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now()
    today_str = f"{now.day} {SWEDISH_MONTHS[now.month]} {now.year}"
    print(f"\n📰 Startar nyhetspodd för {today_str}\n")

    print("1/4 Hämtar nyheter...")
    articles = fetch_news()

    print("2/4 Skriver manus...")
    script = write_script(articles, today_str)

    print("3/4 Genererar ljud...")
    audio_path = text_to_speech(script)

    print("4/4 Skickar till Telegram...")
    send_to_telegram(audio_path, today_str)

    print("\n✅ Klart! Ha en bra dag.\n")

if __name__ == "__main__":
    main()
