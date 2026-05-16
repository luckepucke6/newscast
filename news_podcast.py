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

AZURE_VOICE_EP1 = "sv-SE-SofieNeural"   # Avsnitt 1: Världsnyheter & Sverige
AZURE_VOICE_EP2 = "sv-SE-ErikNeural"      # Avsnitt 2: AI & Teknik — byt till SofieNeural eller HilleviNeural

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
Välj ut 4–5 av de viktigaste nyheterna nedan.

VIKTIGT OM LÄNGD: Manuset ska ta ca 15 minuter att läsa upp högt i lugn takt. \
Det motsvarar 1 800–2 000 ord. Varje nyhet ska behandlas grundligt med \
bakgrund, analys och kontext — inte bara en kort notis. \
Räkna dina ord internt. Om du är under 1 800 — fortsätt och bygg ut.

STRUKTUR FÖR VARJE NYHET — ge varje del ordentligt utrymme:
1. Aktivera minnet (2–3 meningar) — koppla om möjligt till en händelse lyssnaren \
känner till. T.ex: "Om du minns det vi pratade om kring X — det här är nästa kapitel." \
Hoppa naturligt över om ingen rimlig koppling finns.
2. Vad hände (3–4 meningar) — kortfattat och tydligt
3. Varför det spelar roll (4–5 meningar) — för Sverige, för världen, för lyssnaren. \
Ge konkreta exempel på hur det påverkar vanliga människor.
4. Kontext (3–4 meningar) — "Det här är en del av ett större mönster där..." \
Förklara bakgrunden som krävs för att förstå nyheten fullt ut.
5. Vad händer härnäst (2–3 meningar) — vad ska lyssnaren hålla ögonen på

OBLIGATORISK INTRO:
"Hej och välkommen till din dagliga nyhetssammanfattning. Det är {today_str}. \
Idag går vi igenom [antal] nyheter — från Sverige och resten av världen."

OBLIGATORISK AVSLUTNING (ca 80 ord):
"Innan vi avslutar — de viktigaste sakerna från idag: \
1. [konkret punkt] 2. [konkret punkt] 3. [konkret punkt om fler]. \
Kom ihåg dem när du läser nyheter under dagen. Vi hörs imorgon."

TON OCH STIL:
— Tala direkt till lyssnaren med "du"
— Engagerande och pedagogisk, inte en uppläsare
— Varmt men professionellt — kunnig vän, inte kompis
— Förklara begrepp utan jargong

ABSOLUTA KRAV:
— Minst 1 800 ord — bygg ut varje nyhet om du är under
— Skriv BARA manustexten — inga rubriker, noter eller parenteser
— Svenska genomgående

NYHETER:
{articles_text}"""

PROMPT_EP2 = """\
Du är värd för ett teknik- och AI-poddavsnitt. Fokuset är alltid: \
vad innebär det här praktiskt för vanliga människor — inte ett pr-blad \
för produktlanseringar.

Skriv avsnitt 2: AI & Teknik för {today_str}.
Välj ut 3–5 nyheter. Skippa produktlanseringar utan tydlig konsekvens — \
fokusera på vad som faktiskt förändrar något.

VIKTIGT OM LÄNGD: Avsnittet ska ta ca 12 minuter att läsa upp i lugn takt, \
vilket är 1 400–1 600 ord. Varje nyhet ska ha ordentlig fördjupning. \
Räkna dina ord internt — bygg ut med mer praktiska exempel om du är under 1 400.

STRUKTUR FÖR VARJE NYHET — ge varje del utrymme:
1. Aktivera minnet (2–3 meningar) — koppla till något lyssnaren redan vet om AI eller tech.
2. Vad hände (3–4 meningar) — kortfattat
3. Vad det praktiskt innebär (5–6 meningar) — detta är kärnan. \
Ge konkreta exempel: hur påverkas en vanlig person, ett litet företag, en lärare?
4. Kontext i den större AI-utvecklingen (3–4 meningar)
5. Vad ska lyssnaren hålla ögonen på härnäst (2–3 meningar)

OBLIGATORISK INTRO:
"Hej och välkommen till teknikavsnittet. Det är {today_str}. \
Vi dyker ner i [antal] nyheter från AI- och teknikvärlden — \
och framför allt vad de faktiskt innebär för dig."

OBLIGATORISK AVSLUTNING (ca 80 ord):
"Sammanfattningsvis — de viktigaste sakerna från teknikvärlden idag: \
1. [punkt] 2. [punkt] 3. [punkt om fler]. Vi hörs {next_tech_day}."

TON:
— Nyfiken och förklarande — techvän som är bra på att förklara
— Alltid: vad betyder detta praktiskt? Inte bara vad som lanserades.
— Direkt tilltal med "du"

ABSOLUTA KRAV:
— Minst 1 400 ord — bygg ut med fler praktiska exempel om du är under
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
        max_tokens=3500,
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
    """Omvandlar manus till MP3 via Azure Cognitive Services Speech."""
    voice = AZURE_VOICE_EP1 if episode == 1 else AZURE_VOICE_EP2
    path  = f"/tmp/podcast_ep{episode}.mp3"

    speech_config = speechsdk.SpeechConfig(
        subscription=AZURE_SPEECH_KEY,
        region=AZURE_SPEECH_REGION,
    )
    speech_config.speech_synthesis_voice_name = voice
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
    )

    audio_config = speechsdk.audio.AudioOutputConfig(filename=path)
    synthesizer  = speechsdk.SpeechSynthesizer(
        speech_config=speech_config,
        audio_config=audio_config,
    )

    print(f"  Azure TTS: {len(script)} tecken med röst {voice}...")
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

def extend_script(script: str, episode: int, min_words: int) -> str:
    """Förlänger ett för kort manus utan att skriva om det från grunden."""
    current_words = len(script.split())
    extra_needed  = min_words - current_words + 100   # lite marginal
    prompt = f"""Nedanför finns ett nyhets-podcast-manus på {current_words} ord. \
Det behöver vara minst {min_words} ord — det saknas ungefär {extra_needed} ord.

Bygg ut manuset genom att:
— Lägga till mer bakgrund och kontext för varje nyhet
— Ge fler konkreta exempel på hur nyheterna påverkar vanliga människor
— Fördjupa analysen där det finns utrymme

Behåll exakt samma struktur, intro och outro. \
Returnera det kompletta, utbyggda manuset — inget annat.

MANUS ATT BYGGA UT:
{script}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4000,
        temperature=0.5,
    )
    extended = response.choices[0].message.content
    print(f"  Utbyggt manus: {len(extended.split())} ord")
    return extended


def generate_episode(
    episode: int,
    feeds:   dict,
    history: dict,
    today_str: str,
    weekday:   int,
) -> None:
    label   = EPISODE_LABELS[episode]
    min_w   = MIN_WORDS[episode]
    print(f"\n── Avsnitt {episode}: {label} ──")

    articles = fetch_articles(feeds, history)
    if not articles:
        print("  Inga nya artiklar. Hoppar över.")
        return

    print("  Skriver manus...")
    script = write_script(episode, articles, today_str, weekday)

    # Om för kort — försök förlänga (max 2 ggr) innan judge
    for attempt in range(1, MAX_RETRIES + 1):
        if len(script.split()) >= min_w:
            break
        print(f"  För kort ({len(script.split())} ord) — bygger ut (försök {attempt}/{MAX_RETRIES})...")
        script = extend_script(script, episode, min_w)

    print("  Granskar manus...")
    approved, verdict = judge_script(episode, script)
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
    force_ep2 = os.environ.get("FORCE_EPISODE2", "").lower() == "true"
    print(f"\n📰 Nyhetspodd v3 – {today_str}\n")

    history = load_history()

    # Avsnitt 1: varje dag
    generate_episode(1, FEEDS_EP1, history, today_str, weekday)

    # Avsnitt 2: måndag, onsdag, fredag — eller om FORCE_EPISODE2=true
    if weekday in TECH_DAYS or force_ep2:
        if force_ep2 and weekday not in TECH_DAYS:
            print(f"\n(FORCE_EPISODE2 aktiv — kör avsnitt 2 trots {SWEDISH_DAYS[weekday]})")
        generate_episode(2, FEEDS_EP2, history, today_str, weekday)
    else:
        print(f"\nAvsnitt 2 hoppas över idag ({SWEDISH_DAYS[weekday]}) — sänds mån/ons/fre.")

    print("\nSparar historik...")
    save_history(history)
    print(f"\n✅ Klart – {today_str}\n")

    print("\nSparar historik...")
    save_history(history)
    print(f"\n✅ Klart – {today_str}\n")


if __name__ == "__main__":
    main()
