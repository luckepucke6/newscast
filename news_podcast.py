#!/usr/bin/env python3
"""
Daily News Podcast v2
Hämtar nyheter → deduplicerar mot historik → skriver manus → LLM judge → TTS → Telegram
"""

import os
import json
import hashlib
import feedparser
import requests
from openai import OpenAI
from datetime import datetime, timedelta

client          = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
TELEGRAM_TOKEN  = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

HISTORY_FILE  = "seen_urls.json"
HISTORY_DAYS  = 7
MAX_RETRIES   = 2

CATEGORY_ORDER = ["Sverige", "Tech & AI", "Världsnyheter", "Politik"]

FEEDS = {
    "Sverige": (
        "https://news.google.com/rss/search"
        "?q=Sverige+Swedish+news&hl=sv&gl=SE&ceid=SE:sv"
    ),
    "Tech & AI": (
        "https://news.google.com/rss/search"
        "?q=artificial+intelligence+tech&hl=en&gl=US&ceid=US:en"
    ),
    "Världsnyheter": (
        "https://news.google.com/rss/search"
        "?q=world+news+today&hl=en&gl=US&ceid=US:en"
    ),
    "Politik": (
        "https://news.google.com/rss/search"
        "?q=politics+world+today&hl=en&gl=US&ceid=US:en"
    ),
}

ARTICLES_PER_FEED = 3

SWEDISH_MONTHS = {
    1: "januari",  2: "februari", 3: "mars",      4: "april",
    5: "maj",      6: "juni",     7: "juli",       8: "augusti",
    9: "september", 10: "oktober", 11: "november", 12: "december",
}


def swedish_date(dt: datetime) -> str:
    return f"{dt.day} {SWEDISH_MONTHS[dt.month]} {dt.year}"


# ── Historik ──────────────────────────────────────────────────────────────────

def load_history() -> dict:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return {}


def save_history(history: dict) -> None:
    cutoff = (datetime.now() - timedelta(days=HISTORY_DAYS)).isoformat()
    pruned = {k: v for k, v in history.items() if v >= cutoff}
    with open(HISTORY_FILE, "w") as f:
        json.dump(pruned, f, indent=2)
    print(f"  Historik sparad: {len(pruned)} poster")


def article_key(title: str, url: str) -> str:
    return hashlib.md5((title + url).lower().encode()).hexdigest()


# ── Steg 1: Hämta & filtrera nyheter ─────────────────────────────────────────

def fetch_news(history: dict) -> list[dict]:
    articles = []
    now_iso  = datetime.now().isoformat()
    skipped  = 0

    for category in CATEGORY_ORDER:
        feed  = feedparser.parse(FEEDS[category])
        count = 0
        for entry in feed.entries:
            if count >= ARTICLES_PER_FEED:
                break
            title   = entry.title
            url     = entry.get("link", "")
            summary = (
                entry.get("summary", "")[:500]
                .replace("<b>", "").replace("</b>", "")
            )
            key = article_key(title, url)
            if key in history:
                skipped += 1
                continue
            articles.append({
                "category": category,
                "title":    title,
                "url":      url,
                "summary":  summary,
            })
            history[key] = now_iso
            count += 1

    print(f"  {len(articles)} nya artiklar ({skipped} redan sedda)")
    return articles


# ── Steg 2: Skriv manus ───────────────────────────────────────────────────────

def write_script(articles: list[dict], today_str: str) -> str:
    by_category: dict[str, list] = {cat: [] for cat in CATEGORY_ORDER}
    for a in articles:
        by_category[a["category"]].append(a)

    articles_text = ""
    for cat in CATEGORY_ORDER:
        items = by_category.get(cat, [])
        if items:
            articles_text += f"\n=== {cat} ===\n"
            for a in items:
                articles_text += f"Rubrik: {a['title']}\nIngress: {a['summary']}\n\n"

    n = min(len(articles), 10)

    prompt = f"""Du är en erfaren nyhetsuppläsare i stil med Sveriges Radio Ekot. Tonen är saklig, välformulerad och professionell. Inga informella fraser eller vänskapliga tilltal.

Skriv ett podcastmanus på SVENSKA för {today_str}. Manuset ska vara 5–7 minuter långt — det kräver minst 750 ord. Varje nyhet ska behandlas ordentligt med bakgrund och analys, inte bara en mening. Fyll på med mer kontext om du är under.

Välj ut de {n} mest relevanta nyheterna och presentera dem i denna ordning: Sverige → Tech & AI → Världsnyheter → Politik.

STRUKTUR FÖR VARJE NYHET (följ denna för alla):
1. Vad har hänt — sakligt och tydligt (2–3 meningar)
2. Bakgrund och kontext — vad lyssnaren behöver veta (1–2 meningar)
3. Kort analys — vad innebär detta och vad bör man följa framöver (1–2 meningar)

OBLIGATORISK INTRO:
"God morgon. Det är {today_str} och du lyssnar på din dagliga nyhetssammanfattning. I dag går vi igenom {n} nyheter."

OBLIGATORISKT OUTRO:
En mening om vad som är värt att följa den närmaste tiden, sedan:
"Det var nyheterna för {today_str}. Ha en bra dag."

KRAV:
— Minst 800 ord, helst 850–950
— Professionell ton genomgående
— Varje nyhet har alla tre delar: fakta, kontext, analys
— Skriv BARA manustexten — inga rubriker, noter eller parenteser

NYHETER ATT ANVÄNDA:
{articles_text}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2500,
        temperature=0.5,
    )
    script = response.choices[0].message.content
    print(f"  Manus: {len(script.split())} ord")
    return script


# ── Steg 3: LLM judge ────────────────────────────────────────────────────────

def judge_script(script: str) -> tuple[bool, str]:
    words  = len(script.split())
    prompt = f"""Du är en strikt redaktör som granskar ett nyhets-podcast-manus. Bedöm dessa punkter:

1. Längd: minst 750 ord krävs. Faktiskt antal: {words} ord.
2. Ton: saklig och professionell som SR Ekot — inga informella inslag.
3. Struktur: varje nyhet har fakta + bakgrund/kontext + kort analys.
4. Intro: börjar med korrekt datum och antal nyheter.
5. Outro: avslutar med framtidsblick och korrekt datum.

Svara med EXAKT ett av dessa:
GODKÄNT
AVVISAT: [kortfattad orsak, en rad]

Manus:
{script}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=80,
        temperature=0,
    )
    verdict  = response.choices[0].message.content.strip()
    approved = verdict.startswith("GODKÄNT")
    print(f"  Judge: {verdict}")
    return approved, verdict


# ── Steg 4: Text-till-tal ────────────────────────────────────────────────────

def split_for_tts(text: str, max_chars: int = 4000) -> list[str]:
    """Delar upp text vid meningsgränser för att hålla sig under TTS-gränsen."""
    if len(text) <= max_chars:
        return [text]
    chunks, current = [], ""
    for sentence in text.replace("! ", "!\n").replace("? ", "?\n").replace(". ", ".\n").split("\n"):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(current) + len(sentence) + 1 <= max_chars:
            current += sentence + " "
        else:
            if current:
                chunks.append(current.strip())
            current = sentence + " "
    if current:
        chunks.append(current.strip())
    return chunks


def text_to_speech(script: str) -> str:
    chunks = split_for_tts(script)
    print(f"  TTS: {len(chunks)} del(ar), {len(script)} tecken totalt")
    path = "/tmp/podcast_today.mp3"
    with open(path, "wb") as f:
        for i, chunk in enumerate(chunks, 1):
            print(f"  Genererar del {i}/{len(chunks)}...")
            response = client.audio.speech.create(
                model="tts-1",
                voice="echo",
                input=chunk,
                speed=1.0,
            )
            f.write(response.content)
    print(f"  Ljud klart: {os.path.getsize(path) // 1024} KB")
    return path


# ── Steg 5: Telegram ─────────────────────────────────────────────────────────

def send_to_telegram(path: str, today_str: str, n: int) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendAudio"
    with open(path, "rb") as f:
        resp = requests.post(
            url,
            data={
                "chat_id":   TELEGRAM_CHAT_ID,
                "caption":   f"🎙 Nyheter {today_str} · {n} nyheter",
                "performer": "Daglig nyhetssammanfattning",
                "title":     f"Nyheter {today_str}",
            },
            files={"audio": ("podcast.mp3", f, "audio/mpeg")},
            timeout=60,
        )
    if not resp.ok:
        raise RuntimeError(f"Telegram-fel {resp.status_code}: {resp.text}")
    print("  Skickat!")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today_str = swedish_date(datetime.now())
    print(f"\n📰 Nyhetspodd v2 – {today_str}\n")

    print("1/5 Laddar historik & hämtar nyheter...")
    history  = load_history()
    articles = fetch_news(history)
    if not articles:
        print("Inga nya artiklar. Avslutar.")
        return

    print("2/5 Skriver manus...")
    script = write_script(articles, today_str)

    print("3/5 LLM judge granskar...")
    approved, verdict = False, ""
    for attempt in range(1, MAX_RETRIES + 1):
        approved, verdict = judge_script(script)
        if approved:
            break
        if attempt < MAX_RETRIES:
            print(f"  Skriver om manus (försök {attempt + 1}/{MAX_RETRIES})...")
            script = write_script(articles, today_str)
    if not approved:
        print(f"  Skickar ändå — {verdict}")

    print("4/5 Genererar ljud...")
    audio_path = text_to_speech(script)

    print("5/5 Skickar till Telegram...")
    n = min(len(articles), 10)
    send_to_telegram(audio_path, today_str, n)

    print("Sparar historik...")
    save_history(history)

    print(f"\n Klart! {n} nyheter för {today_str}.\n")


if __name__ == "__main__":
    main()
