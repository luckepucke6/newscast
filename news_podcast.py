#!/usr/bin/env python3
"""
Daily News Podcast v3
Avsnitt 1: Världsnyheter & Sverige  — varje dag        (~15 min)
Avsnitt 2: AI & Teknik              — mån, ons, fre    (~12 min)
"""

import os
import json
import hashlib
import feedparser
import requests
import azure.cognitiveservices.speech as speechsdk
from openai import OpenAI
from datetime import datetime, timedelta

client              = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
TELEGRAM_TOKEN      = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID    = os.environ["TELEGRAM_CHAT_ID"]
AZURE_SPEECH_KEY    = os.environ["AZURE_SPEECH_KEY"]
AZURE_SPEECH_REGION = os.environ["AZURE_SPEECH_REGION"]

AZURE_VOICE = "sv-SE-MattiasNeural"   # Byt till sv-SE-ErikNeural för att testa Erik

HISTORY_FILE = "seen_urls.json"
HISTORY_DAYS = 7
MAX_RETRIES  = 2

SWEDISH_MONTHS = {
    1: "januari",  2: "februari", 3: "mars",      4: "april",
    5: "maj",      6: "juni",     7: "juli",       8: "augusti",
    9: "september", 10: "oktober", 11: "november", 12: "december",
}
SWEDISH_DAYS = {
    0: "måndag", 1: "tisdag", 2: "onsdag",
    3: "torsdag", 4: "fredag", 5: "lördag", 6: "söndag",
}
NEXT_TECH_DAY = {0: "onsdag", 1: "onsdag", 2: "fredag", 3: "fredag", 4: "måndag", 5: "måndag", 6: "onsdag"}

TECH_DAYS = {0, 2, 4}   # måndag=0, onsdag=2, fredag=4

FEEDS_EP1 = {
    "Sverige": (
        "https://news.google.com/rss/search"
        "?q=Sverige+Swedish+news&hl=sv&gl=SE&ceid=SE:sv"
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

FEEDS_EP2 = {
    "Tech & AI": (
        "https://news.google.com/rss/search"
        "?q=artificial+intelligence+technology&hl=en&gl=US&ceid=US:en"
    ),
}

EPISODE_LABELS = {
    1: "Världsnyheter & Sverige",
    2: "AI & Teknik",
}

MIN_WORDS = {1: 1800, 2: 1400}


def swedish_date(dt: datetime) -> str:
    return f"{SWEDISH_DAYS[dt.weekday()]} {dt.day} {SWEDISH_MONTHS[dt.month]} {dt.year}"


# ── Historik & deduplicering ──────────────────────────────────────────────────

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
    print(f"  Historik: {len(pruned)} poster sparade")


def article_key(title: str, url: str) -> str:
    return hashlib.md5((title + url).lower().encode()).hexdigest()


# ── Hämta artiklar ────────────────────────────────────────────────────────────

def fetch_articles(feeds: dict, history: dict, max_per_feed: int = 4) -> list[dict]:
    articles = []
    now_iso  = datetime.now().isoformat()
    skipped  = 0

    for category, url in feeds.items():
        feed  = feedparser.parse(url)
        count = 0
        for entry in feed.entries:
            if count >= max_per_feed:
                break
            title   = entry.title
            link    = entry.get("link", "")
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
                "title":    title,
                "url":      link,
                "summary":  summary,
            })
            history[key] = now_iso
            count += 1

    print(f"  {len(articles)} nya artiklar ({skipped} redan sedda)")
    return articles


# ── Promptmallar ──────────────────────────────────────────────────────────────

PROMPT_EP1 = """\
Du är värd för en daglig nyhetspodd. Du är som en kunnig vän som förklarar \
nyheter på ett sätt som faktiskt fastnar — engagerande och pedagogisk, \
inte en torr uppläsare.

Skriv avsnitt 1: Världsnyheter & Sverige för {today_str}.
Manuset ska vara ca 15 minuter, vilket kräver MINST 1 800 ord.
Välj ut 3–5 av de viktigaste nyheterna nedan.

STRUKTUR FÖR VARJE NYHET (använd för alla):
1. Aktivera minnet — koppla om möjligt till en händelse lyssnaren känner till sedan \
tidigare. T.ex: "Om du minns det vi pratade om kring X — det här är nästa kapitel." \
Gör det naturligt; hoppa över om ingen rimlig koppling finns.
2. Vad hände — kortfattat och tydligt (2–3 meningar)
3. Varför det spelar roll — för Sverige, för världen, för dig som lyssnare
4. Kontext — "Det här är en del av ett större mönster där..." (1–2 meningar)
5. Vad händer härnäst — vad ska lyssnaren hålla ögonen på

OBLIGATORISK INTRO:
"Hej och välkommen till din dagliga nyhetssammanfattning. Det är {today_str}. \
Idag går vi igenom [antal] nyheter — från Sverige och resten av världen."

OBLIGATORISK AVSLUTNING (30 sekunder, ca 70 ord):
"Innan vi avslutar — de viktigaste sakerna från idag: \
1. [kort punkt] 2. [kort punkt] 3. [kort punkt om fler]. \
Kom ihåg dem när du läser nyheter under dagen. Vi hörs imorgon."

TON OCH STIL:
— Tala direkt till lyssnaren med "du"
— Engagerande och pedagogisk, inte en uppläsare
— Varmt men professionellt — kunnig vän, inte kompis
— Förklara begrepp utan jargong

KRAV:
— MINST 1 800 ord. Komplettera med mer kontext och fördjupning om du är under.
— Skriv BARA manustexten — inga rubriker, noter eller parenteser
— Svenska genomgående

NYHETER:
{articles_text}"""

PROMPT_EP2 = """\
Du är värd för ett teknik- och AI-poddavsnitt. Fokuset är alltid: \
vad innebär det här praktiskt för vanliga människor — inte ett pr-blad \
för produktlanseringar.

Skriv avsnitt 2: AI & Teknik för {today_str}.
Manuset ska vara ca 12 minuter, vilket kräver MINST 1 400 ord.
Välj ut 3–5 nyheter. Skippa produktlanseringar utan tydlig konsekvens — \
fokusera på vad som faktiskt förändrar något.

STRUKTUR FÖR VARJE NYHET:
1. Aktivera minnet — koppla till något lyssnaren redan vet om AI eller tech. \
T.ex: "Vi pratade förra gången om hur LLM:er funkar — det här är ett praktiskt \
exempel på det." Gör det naturligt.
2. Vad hände — kortfattat
3. Vad det praktiskt innebär för vanliga människor — detta är kärnan, ge det utrymme
4. Kontext i den större AI-utvecklingen
5. Vad ska lyssnaren hålla ögonen på härnäst

OBLIGATORISK INTRO:
"Hej och välkommen till teknikavsnittet. Det är {today_str}. \
Vi dyker ner i [antal] nyheter från AI- och teknikvärlden — \
och framför allt vad de faktiskt innebär för dig."

OBLIGATORISK AVSLUTNING (30 sekunder):
"Sammanfattningsvis — de viktigaste sakerna från teknikvärlden idag: \
1. [punkt] 2. [punkt] 3. [punkt om fler]. Vi hörs {next_tech_day}."

TON:
— Nyfiken och förklarande — techvän som är bra på att förklara
— Alltid: vad betyder detta praktiskt? Inte bara vad som lanserades.
— Direkt tilltal med "du"

KRAV:
— MINST 1 400 ord
— Skriv BARA manustext — inga rubriker
— Svenska genomgående

NYHETER:
{articles_text}"""


# ── Skriv manus ───────────────────────────────────────────────────────────────

def write_script(episode: int, articles: list[dict], today_str: str, weekday: int) -> str:
    articles_text = "\n".join([
        f"[{a['category']}] {a['title']}\n{a['summary']}\n"
        for a in articles
    ])
    template = PROMPT_EP1 if episode == 1 else PROMPT_EP2
    prompt   = template.format(
        today_str=today_str,
        articles_text=articles_text,
        next_tech_day=NEXT_TECH_DAY.get(weekday, "nästa gång"),
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2800,
        temperature=0.65,
    )
    script = response.choices[0].message.content
    print(f"  Manus: {len(script.split())} ord")
    return script


# ── LLM judge ─────────────────────────────────────────────────────────────────

def judge_script(episode: int, script: str) -> tuple[bool, str]:
    words = len(script.split())
    min_w = MIN_WORDS[episode]
    prompt = f"""Granska detta nyhets-podcast-manus (avsnitt {episode}). Bedöm:

1. Längd: minst {min_w} ord krävs. Faktiskt: {words} ord.
2. Struktur: varje nyhet har minnesaktivering (om möjligt), fakta, relevans, kontext och nästa steg.
3. Ton: pedagogisk och engagerande, direkt tilltal med "du".
4. Avslutning: 30-sekunders summering med numrerade punkter.
5. Intro: presenterar datum och ämnesområde.

Svara EXAKT med ett av:
GODKÄNT
AVVISAT: [orsak på en rad]

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


# ── TTS med chunkning ─────────────────────────────────────────────────────────

def text_to_speech(script: str, episode: int) -> str:
    """Omvandlar manus till MP3 via Azure Cognitive Services Speech (Mattias Neural)."""
    path = f"/tmp/podcast_ep{episode}.mp3"

    speech_config = speechsdk.SpeechConfig(
        subscription=AZURE_SPEECH_KEY,
        region=AZURE_SPEECH_REGION,
    )
    speech_config.speech_synthesis_voice_name = AZURE_VOICE
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
    )

    audio_config = speechsdk.audio.AudioOutputConfig(filename=path)
    synthesizer  = speechsdk.SpeechSynthesizer(
        speech_config=speech_config,
        audio_config=audio_config,
    )

    print(f"  Azure TTS: {len(script)} tecken med röst {AZURE_VOICE}...")
    result = synthesizer.speak_text_async(script).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print(f"  Ljud: {os.path.getsize(path) // 1024} KB")
        return path
    elif result.reason == speechsdk.ResultReason.Canceled:
        details = result.cancellation_details
        raise RuntimeError(f"Azure TTS avbruten: {details.reason} – {details.error_details}")
    else:
        raise RuntimeError(f"Azure TTS misslyckades: {result.reason}")


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_to_telegram(path: str, episode: int, today_str: str, n: int) -> None:
    label = EPISODE_LABELS[episode]
    url   = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendAudio"
    with open(path, "rb") as f:
        resp = requests.post(
            url,
            data={
                "chat_id":   TELEGRAM_CHAT_ID,
                "caption":   f"🎙 Avsnitt {episode}: {label}\n{today_str} · {n} nyheter",
                "performer": label,
                "title":     f"Avsnitt {episode} – {today_str}",
            },
            files={"audio": (f"avsnitt{episode}.mp3", f, "audio/mpeg")},
            timeout=120,
        )
    if not resp.ok:
        raise RuntimeError(f"Telegram-fel {resp.status_code}: {resp.text}")
    print(f"  Avsnitt {episode} skickat till Telegram!")


# ── Generera ett avsnitt ──────────────────────────────────────────────────────

def generate_episode(
    episode: int,
    feeds:   dict,
    history: dict,
    today_str: str,
    weekday:   int,
) -> None:
    label = EPISODE_LABELS[episode]
    print(f"\n── Avsnitt {episode}: {label} ──")

    articles = fetch_articles(feeds, history)
    if not articles:
        print("  Inga nya artiklar. Hoppar över.")
        return

    print("  Skriver manus...")
    script = write_script(episode, articles, today_str, weekday)

    print("  Granskar manus...")
    approved, verdict = False, ""
    for attempt in range(1, MAX_RETRIES + 1):
        approved, verdict = judge_script(episode, script)
        if approved:
            break
        if attempt < MAX_RETRIES:
            print(f"  Skriver om (försök {attempt + 1}/{MAX_RETRIES})...")
            script = write_script(episode, articles, today_str, weekday)
    if not approved:
        print(f"  Skickar ändå — {verdict}")

    audio = text_to_speech(script, episode)
    n     = min(len(articles), 5)
    send_to_telegram(audio, episode, today_str, n)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    now       = datetime.now()
    weekday   = now.weekday()
    today_str = swedish_date(now)
    print(f"\n📰 Nyhetspodd v3 – {today_str}\n")

    history = load_history()

    # Avsnitt 1: varje dag
    generate_episode(1, FEEDS_EP1, history, today_str, weekday)

    # Avsnitt 2: måndag, onsdag, fredag
    if weekday in TECH_DAYS:
        generate_episode(2, FEEDS_EP2, history, today_str, weekday)
    else:
        print(f"\nAvsnitt 2 hoppas över idag ({SWEDISH_DAYS[weekday]}) — sänds mån/ons/fre.")

    print("\nSparar historik...")
    save_history(history)
    print(f"\n✅ Klart – {today_str}\n")


if __name__ == "__main__":
    main()
