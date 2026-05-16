#!/usr/bin/env python3
"""
Daily News Podcast v5
Avsnitt 1: Världsnyheter & Sverige  — varje dag
Avsnitt 2: AI & Teknik              — mån, ons, fre

TTS: ElevenLabs Flash v2.5
"""

import os
import json
import hashlib
import traceback
import feedparser
import requests
from elevenlabs.client import ElevenLabs
from openai import OpenAI
from datetime import datetime, timedelta

openai_client       = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
eleven              = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
TELEGRAM_TOKEN      = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID    = os.environ["TELEGRAM_CHAT_ID"]

# Röst-IDs — byt på elevenlabs.io/voice-library om du vill testa andra
# EP1 (Världsnyheter): kvinnlig röst
VOICE_EP1 = os.environ.get("ELEVENLABS_VOICE_EP1", "XrExE9yKIg1WjnnlVkGX")  # Matilda
# EP2 (AI & Teknik): manlig röst
VOICE_EP2 = os.environ.get("ELEVENLABS_VOICE_EP2", "pNInz6obpgDQGcFmaJgB")  # Adam

ELEVEN_MODEL = "eleven_flash_v2_5"

HISTORY_FILE     = "seen_urls.json"
MEMORY_FILE      = "topic_memory.json"   # Ämnesminne: sammanfattningar per dag
HISTORY_DAYS     = 7
MAX_RETRIES      = 2
RELEVANCE_CUTOFF  = 7    # Hårdare filter för EP1 — bara de bästa artiklarna
EP1_MAX_ARTICLES  = 8    # Max antal artiklar att ta med i EP1 efter filter
EP1_ARTICLES_FEED = 6    # Fler kandidater per källa → bättre urval

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
    # Svenska källor
    "SVT":          "https://www.svt.se/rss.xml",
    "Omni":         "https://omni.se/rss",
    "DN":           "https://www.dn.se/rss/",
    # Google News aggregat
    "Sverige":      "https://news.google.com/rss/search?q=Sverige&hl=sv&gl=SE&ceid=SE:sv",
    "Världsnyheter": "https://news.google.com/rss/search?q=world+news+today&hl=en&gl=US&ceid=US:en",
    "Politik":      "https://news.google.com/rss/search?q=politics+world+today&hl=en&gl=US&ceid=US:en",
}

FEEDS_EP2 = {
    # Breda tech-medier
    "The Verge":          "https://www.theverge.com/rss/index.xml",
    "Wired":              "https://www.wired.com/feed/rss",
    "Ars Technica":       "https://feeds.arstechnica.com/arstechnica/index",
    # Akademiskt / djupare analys
    "MIT Tech Review":    "https://www.technologyreview.com/feed/",
    # Startup & business
    "TechCrunch":         "https://techcrunch.com/feed/",
    "VentureBeat":        "https://venturebeat.com/feed/",
    # Google News AI-aggregat som backup
    "Google AI":          "https://news.google.com/rss/search?q=artificial+intelligence+technology&hl=en&gl=US&ceid=US:en",
}

EPISODE_LABELS = {
    1: "Världsnyheter & Sverige",
    2: "AI & Teknik",
}

MIN_WORDS = {1: 1300, 2: 1100}   # EP1: ~11 min, EP2: ~9 min


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


# ── Väder ─────────────────────────────────────────────────────────────────────

def fetch_weather() -> str:
    """Hämtar aktuellt väder för Stockholm via Open-Meteo (gratis, ingen API-nyckel)."""
    WMO_CODES = {
        0: "klart", 1: "mestadels klart", 2: "delvis molnigt", 3: "mulet",
        45: "dimmigt", 48: "isbildande dimma",
        51: "lätt duggregn", 53: "duggregn", 55: "kraftigt duggregn",
        61: "lätt regn", 63: "regn", 65: "kraftigt regn",
        71: "lätt snöfall", 73: "snöfall", 75: "kraftigt snöfall",
        80: "lätta regnskurar", 81: "regnskurar", 82: "kraftiga regnskurar",
        95: "åskväder", 99: "åskväder med hagel",
    }
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
        data    = resp.json()["current"]
        temp    = round(data["temperature_2m"])
        code    = data["weathercode"]
        desc    = WMO_CODES.get(code, "växlande väder")
        weather = f"{temp} grader och {desc} i Stockholm"
        print(f"  Väder: {weather}")
        return weather
    except Exception as e:
        print(f"  Väder ej tillgängligt: {e}")
        return ""


# ── Relevansfilter ────────────────────────────────────────────────────────────

def filter_by_relevance(articles: list[dict]) -> list[dict]:
    """GPT betygsätter EP1-artiklar 1–10, filtrerar bort under cutoff och begränsar till max antal."""
    if not articles:
        return articles

    lines = "\n".join([
        f"{i+1}. [{a['category']}] {a['title']}"
        for i, a in enumerate(articles)
    ])
    prompt = f"""Betygsätt följande nyhetsrubriker för en daglig nyhetspodd om världsnyheter, svensk politik och samhälle.
Ge varje rubrik ett betyg 1–10 där 10 = mycket relevant och viktig nyhet, 1 = irrelevant eller ointressant.
Var hård — bara genuint viktiga nyheter ska få 7 eller högre.

Svara ENDAST med ett JSON-objekt i detta format (inga förklaringar):
{{"scores": [8, 3, 7, ...]}}

Rubriker:
{lines}"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0,
        )
        raw    = response.choices[0].message.content.strip()
        scores = json.loads(raw)["scores"]

        # Sortera efter betyg, filtrera under cutoff, begränsa till max
        scored   = sorted(zip(scores, articles), key=lambda x: x[0], reverse=True)
        filtered = [a for s, a in scored if s >= RELEVANCE_CUTOFF][:EP1_MAX_ARTICLES]

        removed = len(articles) - len(filtered)
        print(f"  Relevansfilter: {len(filtered)} kvar av {len(articles)} (cutoff={RELEVANCE_CUTOFF}, max={EP1_MAX_ARTICLES}, borttagna={removed})")
        return filtered if filtered else articles[:EP1_MAX_ARTICLES]
    except Exception as e:
        print(f"  Relevansfilter misslyckades ({e}) — kör med de första {EP1_MAX_ARTICLES}")
        return articles[:EP1_MAX_ARTICLES]


# ── Ämnesminne ────────────────────────────────────────────────────────────────

def load_memory() -> list[dict]:
    """Laddar ämnesminne (senaste 7 dagarnas sända nyheter)."""
    if not os.path.exists(MEMORY_FILE):
        return []
    try:
        with open(MEMORY_FILE) as f:
            entries = json.load(f)
        cutoff  = (datetime.now() - timedelta(days=HISTORY_DAYS)).isoformat()
        return [e for e in entries if e.get("date", "") >= cutoff]
    except Exception:
        return []


def save_memory(memory: list[dict], new_entry: dict) -> None:
    """Lägger till en ny post och sparar (max 7 dagars historik)."""
    memory.append(new_entry)
    cutoff  = (datetime.now() - timedelta(days=HISTORY_DAYS)).isoformat()
    pruned  = [e for e in memory if e.get("date", "") >= cutoff]
    with open(MEMORY_FILE, "w") as f:
        json.dump(pruned, f, ensure_ascii=False, indent=2)


def memory_to_context(memory: list[dict], episode: int) -> str:
    """Formaterar minnesposter till en kontext-sträng för GPT-prompten."""
    relevant = [e for e in memory if e.get("episode") == episode]
    if not relevant:
        return ""
    lines = []
    for entry in relevant[-5:]:   # Max 5 tidigare avsnitt
        lines.append(f"\n{entry['date'][:10]}:")
        for h in entry.get("headlines", []):
            lines.append(f"  - {h}")
    return "\n".join(lines)


def extract_headlines(script: str, articles: list[dict]) -> list[str]:
    """Extraherar korta rubriksammanfattningar från artiklarna för minnesfilen."""
    return [f"[{a['category']}] {a['title'][:80]}" for a in articles[:8]]


# ── Felnotifiering ────────────────────────────────────────────────────────────

def notify_error(message: str) -> None:
    """Skickar ett textmeddelande till Telegram vid fel."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text":    f"⚠️ Nyhetspodd kraschade:\n\n{message[:1000]}",
            },
            timeout=10,
        )
    except Exception:
        pass   # Om Telegram också är nere — ge upp tyst


# ── Promptmallar ──────────────────────────────────────────────────────────────

PROMPT_EP1 = """\
Du är värd för en daglig nyhetspodd. Du är som en kunnig vän som förklarar \
nyheter på ett sätt som faktiskt fastnar — engagerande och pedagogisk, \
inte en torr uppläsare.

Skriv avsnitt 1: Världsnyheter & Sverige för {today_str}.

URVAL OCH ORDNING:
Välj ut 6–8 av de mest nyhetsvärda artiklarna nedan. \
Sortera dem i den ordning du bedömer ger bäst flöde och nyhetsvärde — \
börja med det viktigaste, men tänk på variation mellan ämnen.

LÄNGD: 10–12 minuter, ca 1 300–1 500 ord. Kärnfullt, ingen utfyllnad.

STRUKTUR PER NYHET — använd omdöme:
1. Vad hände (2–3 meningar) — alltid med
2. Varför det spelar roll / hur det påverkar (2–3 meningar) — bara för viktiga \
eller komplexa nyheter där det tillför något. Hoppa över för korta notiser.
3. Kort analys eller vad som händer härnäst (1–2 meningar) — bara om relevant

OBLIGATORISK INTRO:
"Hej och välkommen till din dagliga nyhetssammanfattning. Det är {today_str}. \
{weather_line}\
Idag går vi igenom [antal] nyheter."

OBLIGATORISK AVSLUTNING (ca 60 ord):
"Det var nyheterna för idag. De tre viktigaste sakerna att ta med sig: \
1. [punkt] 2. [punkt] 3. [punkt]. Vi hörs imorgon."

TON OCH STIL:
— Direkt tilltal med "du"
— Engagerande och pedagogisk — kunnig vän, inte uppläsare
— Naturliga övergångar mellan nyheter
— Förklara begrepp utan jargong

TALSPRÅK OCH RYTM — viktigt för hur det låter uppläst:
— Variera meningslängden. Blanda korta och längre meningar medvetet.
— Lägg in naturliga andningspauser med tankstreck eller punkt där du vill ha paus: \
"Det här är en stor förändring — och den kommer snabbt."
— Undvik långa bisatskedjor. Dela upp dem i separata meningar.
— Skriv som du pratar, inte som du skriver. "Det är" inte "detta är".

ABSOLUTA KRAV:
— Skriv BARA manustexten — inga rubriker, noter eller parenteser
— Svenska genomgående

NYHETER:
{articles_text}"""

PROMPT_EP2 = """\
Du är värd för ett bildande tech- och AI-poddavsnitt. Målet är att lyssnaren \
efter varje avsnitt ska förstå både hur tekniken fungerar och hur den påverkar \
samhälle och vardag.

Skriv avsnitt 2: AI & Teknik för {today_str}.
Välj ut 4–6 nyheter. Skippa rena produktlanseringar utan konsekvens. \
Sortera efter bildningsvärde och nyhetsvärde — börja med det mest signifikanta.

PERSPEKTIV ATT TÄCKA PER NYHET (väv in naturligt, inte som en lista):
— Vad hände konkret
— Hur tekniken bakom fungerar, förklarat enkelt
— Vad det förändrar i samhället — jobb, demokrati, ekonomi, vardag
— Ett konkret vardagsscenario: "Tänk dig att du är lärare / småföretagare / \
förälder — då innebär detta att..."

Inte alla perspektiv passar varje nyhet — använd det som är relevant. \
Det viktigaste är att det låter naturligt och pedagogiskt, inte som ett formulär.

OBLIGATORISK INTRO:
"Hej och välkommen till teknikavsnittet. Det är {today_str}. \
Idag går vi igenom [antal] nyheter — och som vanligt fokuserar vi på \
vad de faktiskt innebär för dig och samhället runt om dig."

OBLIGATORISK AVSLUTNING (ca 70 ord):
"Det var teknikavsnittet för idag. Tre saker att ta med sig: \
1. [vad som hänt] 2. [samhällspåverkan] \
3. [något att tänka på eller följa]. Vi hörs {next_tech_day}."

TON OCH STIL:
— Pedagogisk och nyfiken — kunnig vän som tycker det är kul att förklara
— Direkt tilltal med "du"
— Koppla alltid det abstrakta till det konkreta
— Låt perspektiven flöda naturligt — undvik att det låter som punktlistor

TALSPRÅK OCH RYTM — viktigt för hur det låter uppläst:
— Variera meningslängden. Blanda korta och längre meningar medvetet.
— Lägg in naturliga andningspauser med tankstreck eller punkt: \
"Det här låter tekniskt — men det berör dig direkt."
— Undvik långa bisatskedjor. Dela upp dem.
— Skriv som du pratar: "det är" inte "detta är", "du kan" inte "man kan".

ABSOLUTA KRAV:
— Minst 1 400 ord
— Skriv BARA manustext — inga rubriker eller noter
— Svenska genomgående

NYHETER:
{articles_text}"""


# ── Skriv manus ───────────────────────────────────────────────────────────────

def write_script(
    episode: int,
    articles: list[dict],
    today_str: str,
    weekday: int,
    weather: str = "",
) -> str:
    articles_text = "\n".join([
        f"[{a['category']}] {a['title']}\n{a['summary']}\n"
        for a in articles
    ])

    weather_line = f"Det är {weather} idag. " if weather and episode == 1 else ""

    template = PROMPT_EP1 if episode == 1 else PROMPT_EP2
    prompt   = template.format(
        today_str=today_str,
        articles_text=articles_text,
        next_tech_day=NEXT_TECH_DAY.get(weekday, "nästa gång"),
        weather_line=weather_line,
    )
    response = openai_client.chat.completions.create(
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
2. Struktur: varje nyhet har fakta, relevans och kort analys.
3. Ton: pedagogisk och engagerande, direkt tilltal med "du".
4. Avslutning: summering med numrerade punkter.
5. Intro: presenterar datum och antal nyheter.

Svara EXAKT med ett av:
GODKÄNT
AVVISAT: [orsak på en rad]

Manus:
{script}"""

    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=80,
        temperature=0,
    )
    verdict  = response.choices[0].message.content.strip()
    approved = verdict.startswith("GODKÄNT")
    print(f"  Judge: {verdict}")
    return approved, verdict


# ── TTS: ElevenLabs Flash v2.5 ───────────────────────────────────────────────

# Siffror som ElevenLabs Flash har svårt med på svenska — skrivs ut som ord
NUMBER_REPLACEMENTS = {
    "2020": "två tusen tjugo",
    "2021": "två tusen tjugoett",
    "2022": "två tusen tjugotvå",
    "2023": "två tusen tjugotre",
    "2024": "två tusen tjugofyra",
    "2025": "två tusen tjugofem",
    "2026": "två tusen tjugosex",
    "2027": "två tusen tjugosju",
    "2028": "två tusen tjugoåtta",
    "2029": "två tusen tjugonio",
    "2030": "två tusen trettio",
}

def preprocess_script(text: str) -> str:
    """Skriver ut siffror som ElevenLabs Flash missar på svenska."""
    for number, spoken in NUMBER_REPLACEMENTS.items():
        text = text.replace(number, spoken)
    return text


def text_to_speech(script: str, episode: int) -> str:
    """Omvandlar manus till MP3 via ElevenLabs Flash v2.5."""
    voice_id = VOICE_EP1 if episode == 1 else VOICE_EP2
    path     = f"/tmp/podcast_ep{episode}.mp3"

    print(f"  ElevenLabs Flash: {len(script)} tecken, röst {voice_id}...")
    try:
        audio_stream = eleven.text_to_speech.convert(
            voice_id=voice_id,
            text=preprocess_script(script),
            model_id=ELEVEN_MODEL,
            language_code="sv",          # Låser svenska
            output_format="mp3_44100_128",
        )
        with open(path, "wb") as f:
            for chunk in audio_stream:
                f.write(chunk)
        print(f"  Ljud: {os.path.getsize(path) // 1024} KB")
        return path
    except Exception as e:
        raise RuntimeError(f"ElevenLabs TTS misslyckades: {e}")


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

    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4000,
        temperature=0.5,
    )
    extended = response.choices[0].message.content
    print(f"  Utbyggt manus: {len(extended.split())} ord")
    return extended


def generate_episode(
    episode:    int,
    feeds:      dict,
    history:    dict,
    today_str:  str,
    weekday:    int,
    weather:    str = "",
    used_titles: set | None = None,
) -> set:
    """Returnerar set med titlar som användes, så EP2 kan undvika samma nyheter."""
    label = EPISODE_LABELS[episode]
    min_w = MIN_WORDS[episode]
    print(f"\n── Avsnitt {episode}: {label} ──")

    max_per_feed = EP1_ARTICLES_FEED if episode == 1 else 4
    articles = fetch_articles(feeds, history, max_per_feed=max_per_feed)

    # Filtrera bort artiklar som EP1 redan använt (koordinering)
    if used_titles:
        before = len(articles)
        articles = [a for a in articles if a["title"] not in used_titles]
        print(f"  Koordinering: {before - len(articles)} artiklar överlappade med avsnitt 1")

    if not articles:
        print("  Inga nya artiklar. Hoppar över.")
        return used_titles or set()

    # Relevansfilter bara för EP1
    if episode == 1:
        print("  Filtrerar på relevans...")
        articles = filter_by_relevance(articles)

    print("  Skriver manus...")
    script = write_script(episode, articles, today_str, weekday, weather)

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
    n     = len(articles)
    send_to_telegram(audio, episode, today_str, n)

    return {a["title"] for a in articles}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    now       = datetime.now()
    weekday   = now.weekday()
    today_str = swedish_date(now)
    force_ep2 = os.environ.get("FORCE_EPISODE2", "").lower() == "true"
    print(f"\n📰 Nyhetspodd v4 – {today_str}\n")

    print("Förbereder...")
    history = load_history()
    weather = fetch_weather()

    # EP1 — kör alltid, returnera titlar som använts
    used_titles = generate_episode(1, FEEDS_EP1, history, today_str, weekday, weather)

    # EP2 — mån/ons/fre, skickar med used_titles för koordinering
    if weekday in TECH_DAYS or force_ep2:
        if force_ep2 and weekday not in TECH_DAYS:
            print(f"\n(FORCE_EPISODE2 aktiv — kör avsnitt 2 trots {SWEDISH_DAYS[weekday]})")
        generate_episode(2, FEEDS_EP2, history, today_str, weekday, used_titles=used_titles)
    else:
        print(f"\nAvsnitt 2 hoppas över idag ({SWEDISH_DAYS[weekday]}) — sänds mån/ons/fre.")

    print("\nSparar historik...")
    save_history(history)
    print(f"\n✅ Klart – {today_str}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        error_msg = traceback.format_exc()
        print(f"\n💥 Fel:\n{error_msg}")
        notify_error(error_msg)
        raise
