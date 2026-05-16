"""Script generation: writing, judging, extending, and preprocessing."""
import json
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Date/number constants ────────────────────────────────────────────────────

SWEDISH_MONTHS = {
    1: "januari", 2: "februari", 3: "mars", 4: "april",
    5: "maj", 6: "juni", 7: "juli", 8: "augusti",
    9: "september", 10: "oktober", 11: "november", 12: "december",
}
SWEDISH_DAYS = {
    0: "måndag", 1: "tisdag", 2: "onsdag",
    3: "torsdag", 4: "fredag", 5: "lördag", 6: "söndag",
}
NEXT_TECH_DAY = {
    0: "onsdag", 1: "onsdag", 2: "fredag",
    3: "fredag", 4: "måndag", 5: "måndag", 6: "onsdag",
}
TECH_DAYS = {0, 2, 4}

SWEDISH_NUMBERS = {
    1: "första", 2: "andra", 3: "tredje", 4: "fjärde", 5: "femte",
    6: "sjätte", 7: "sjunde", 8: "åttonde", 9: "nionde", 10: "tionde",
    11: "elfte", 12: "tolfte", 13: "trettonde", 14: "fjortonde", 15: "femtonde",
    16: "sextonde", 17: "sjuttonde", 18: "artonde", 19: "nittonde", 20: "tjugonde",
    21: "tjugoförsta", 22: "tjugoandra", 23: "tjugotredje", 24: "tjugofjärde",
    25: "tjugofemte", 26: "tjugosjätte", 27: "tjugosjunde", 28: "tjugoåttonde",
    29: "tjugonionde", 30: "trettionde", 31: "trettioförsta",
}

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


def swedish_date(dt: datetime) -> str:
    day = SWEDISH_NUMBERS[dt.day]
    month = SWEDISH_MONTHS[dt.month]
    year = NUMBER_REPLACEMENTS.get(str(dt.year), str(dt.year))
    return f"{SWEDISH_DAYS[dt.weekday()]} den {day} {month} {year}"


def preprocess_script(text: str) -> str:
    """Skriver ut siffror som ElevenLabs Flash missar på svenska."""
    for number, spoken in NUMBER_REPLACEMENTS.items():
        text = text.replace(number, spoken)
    return text


def _dynamic_length_params(n_articles: int, base_min: int, base_max: int) -> tuple:
    """Returns (min_words, max_words, is_slow_day) based on article count."""
    if n_articles <= 3:
        return int(base_min * 0.65), int(base_max * 0.65), True
    elif n_articles <= 5:
        return int(base_min * 0.85), int(base_max * 0.85), False
    else:
        return base_min, base_max, False


# ── Prompt templates ─────────────────────────────────────────────────────────

PROMPT_EP1 = """\
Du är värd för en daglig nyhetspodd. Du är som en kunnig vän som förklarar \
nyheter på ett sätt som faktiskt fastnar — engagerande och pedagogisk, \
inte en torr uppläsare.

Skriv avsnitt 1: Världsnyheter & Sverige för {today_str}.

URVAL OCH ORDNING:
Välj ut 6–8 av de mest nyhetsvärda artiklarna nedan. \
Sortera dem i den ordning du bedömer ger bäst flöde och nyhetsvärde — \
börja med det viktigaste, men tänk på variation mellan ämnen.

LÄNGD: {length_instruction}. Kärnfullt, ingen utfyllnad.

STRUKTUR PER NYHET — använd omdöme:
1. Vad hände (2–3 meningar) — alltid med
2. Varför det spelar roll / hur det påverkar (2–3 meningar) — bara för viktiga \
eller komplexa nyheter där det tillför något. Hoppa över för korta notiser.
3. Kort analys eller vad som händer härnäst (1–2 meningar) — bara om relevant

OBLIGATORISK INTRO:
"Hej och välkommen till din dagliga nyhetssammanfattning. Det är {today_str}. \
{weather_line}\
{slow_day_line}\
Idag går vi igenom [antal] nyheter."

OBLIGATORISK AVSLUTNING (ca 60 ord):
"Det var nyheterna för idag. De tre viktigaste sakerna att ta med sig: \
1. [punkt] 2. [punkt] 3. [punkt]. Vi hörs imorgon."

TON OCH STIL:
— Direkt tilltal med "du"
— Engagerande och pedagogisk — kunnig vän, inte uppläsare
— Naturliga övergångar mellan nyheter
— Förklara begrepp utan jargong

KÄLLHÄNVISNINGAR — viktigt: Nämn alltid källan naturligt i texten när du presenterar en nyhet. \
Exempel: "Enligt SVT...", "Reuters rapporterar att...", "DN skriver att...", "SR Ekot berättar om...". \
Det ökar trovärdigheten.

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

LÄNGD: {length_instruction}.

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
{slow_day_line}\
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

KÄLLHÄNVISNINGAR — viktigt: Nämn alltid källan naturligt i texten när du presenterar en nyhet. \
Exempel: "Enligt The Verge...", "MIT Technology Review rapporterar att...", \
"TechCrunch skriver att...", "Wired berättar om...". Det ökar trovärdigheten.

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


# ── Script writing ───────────────────────────────────────────────────────────

def write_script(
    episode: int,
    articles: list,
    today_str: str,
    weekday: int,
    cfg: dict,
    openai_client,
    weather: str = "",
    cost_tracker=None,
    max_retries: int = 3,
) -> str:
    ep_cfg = cfg["episodes"][f"ep{episode}"]
    base_min = ep_cfg["min_words"]
    base_max = ep_cfg["max_words"]

    min_words, max_words, is_slow = _dynamic_length_params(len(articles), base_min, base_max)
    length_instruction = f"{min_words}–{max_words} ord"
    slow_day_line = (
        "Lite lugnare nyhetsdag idag, men det finns ändå saker värda att lyfta. "
        if is_slow else ""
    )

    articles_text = "\n".join([
        f"[{a['category']}] {a['title']}\n{a['summary']}\n"
        for a in articles
    ])
    weather_line = f"Det är {weather} idag. " if weather and episode == 1 else ""

    template = PROMPT_EP1 if episode == 1 else PROMPT_EP2
    prompt = template.format(
        today_str=today_str,
        articles_text=articles_text,
        next_tech_day=NEXT_TECH_DAY.get(weekday, "nästa gång"),
        weather_line=weather_line,
        slow_day_line=slow_day_line,
        length_instruction=length_instruction,
    )

    model = cfg["openai"]["model"]
    last_exc = None
    for attempt in range(max_retries):
        try:
            response = openai_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=3500,
                temperature=0.65,
            )
            if cost_tracker:
                cost_tracker.add_gpt4o(
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                )
            script = response.choices[0].message.content
            logger.info("Manus: %d ord", len(script.split()))
            return script
        except Exception as e:
            last_exc = e
            wait = 2 ** attempt
            logger.warning("write_script försök %d misslyckades: %s — väntar %ds", attempt + 1, e, wait)
            time.sleep(wait)
    raise RuntimeError(f"write_script: alla försök misslyckades: {last_exc}")


def judge_script(
    episode: int,
    script: str,
    cfg: dict,
    openai_client,
    cost_tracker=None,
    max_retries: int = 3,
) -> tuple:
    ep_cfg = cfg["episodes"][f"ep{episode}"]
    min_w = ep_cfg["min_words"]
    words = len(script.split())
    model = cfg["openai"]["model"]

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

    last_exc = None
    for attempt in range(max_retries):
        try:
            response = openai_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=80,
                temperature=0,
            )
            if cost_tracker:
                cost_tracker.add_gpt4o(
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                )
            verdict = response.choices[0].message.content.strip()
            approved = verdict.startswith("GODKÄNT")
            logger.info("Judge: %s", verdict)
            return approved, verdict
        except Exception as e:
            last_exc = e
            wait = 2 ** attempt
            logger.warning("judge_script försök %d misslyckades: %s — väntar %ds", attempt + 1, e, wait)
            time.sleep(wait)
    raise RuntimeError(f"judge_script: alla försök misslyckades: {last_exc}")


def extend_script(
    script: str,
    episode: int,
    min_words: int,
    cfg: dict,
    openai_client,
    cost_tracker=None,
    max_retries: int = 3,
) -> str:
    current_words = len(script.split())
    extra_needed = min_words - current_words + 100
    model = cfg["openai"]["model"]

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

    last_exc = None
    for attempt in range(max_retries):
        try:
            response = openai_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4000,
                temperature=0.5,
            )
            if cost_tracker:
                cost_tracker.add_gpt4o(
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                )
            extended = response.choices[0].message.content
            logger.info("Utbyggt manus: %d ord", len(extended.split()))
            return extended
        except Exception as e:
            last_exc = e
            wait = 2 ** attempt
            logger.warning("extend_script försök %d misslyckades: %s — väntar %ds", attempt + 1, e, wait)
            time.sleep(wait)
    raise RuntimeError(f"extend_script: alla försök misslyckades: {last_exc}")


def filter_by_relevance(
    articles: list,
    cfg: dict,
    openai_client,
    cost_tracker=None,
    max_retries: int = 3,
) -> list:
    """GPT betygsätter EP1-artiklar 1–10, filtrerar under cutoff och begränsar till max antal."""
    if not articles:
        return articles

    ep_cfg = cfg["episodes"]["ep1"]
    cutoff = ep_cfg["relevance_cutoff"]
    max_articles = ep_cfg["max_articles"]
    model = cfg["openai"]["model"]

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

    last_exc = None
    for attempt in range(max_retries):
        try:
            response = openai_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0,
            )
            if cost_tracker:
                cost_tracker.add_gpt4o(
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                )
            raw = response.choices[0].message.content.strip()
            # Strip markdown code fences if GPT wraps the JSON in ```json ... ```
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            scores = json.loads(raw)["scores"]
            scored = sorted(zip(scores, articles), key=lambda x: x[0], reverse=True)
            filtered = [a for s, a in scored if s >= cutoff][:max_articles]
            removed = len(articles) - len(filtered)
            logger.info(
                "Relevansfilter: %d kvar av %d (cutoff=%d, max=%d, borttagna=%d)",
                len(filtered), len(articles), cutoff, max_articles, removed,
            )
            return filtered if filtered else articles[:max_articles]
        except Exception as e:
            last_exc = e
            wait = 2 ** attempt
            logger.warning("filter_by_relevance försök %d misslyckades: %s — väntar %ds", attempt + 1, e, wait)
            time.sleep(wait)

    logger.error("filter_by_relevance misslyckades: %s — returnerar de första %d", last_exc, max_articles)
    return articles[:max_articles]
