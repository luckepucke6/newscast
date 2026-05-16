"""Text-to-speech via OpenAI TTS med automatisk chunkning (max 4096 tecken/anrop)."""
import logging
import os
import time

from script import preprocess_script

logger = logging.getLogger(__name__)

MAX_CHARS = 4000  # Lite under 4096 för säkerhetsmarginal


def _split_chunks(text: str, max_chars: int = MAX_CHARS) -> list:
    """Delar upp text i bitar på max max_chars tecken vid stycke- eller meningsgränser."""
    chunks = []
    current = ""

    for paragraph in text.split("\n"):
        # Om ett enstaka stycke är för långt, dela på meningar
        if len(paragraph) > max_chars:
            sentences = paragraph.replace(". ", ".\n").split("\n")
            for sentence in sentences:
                if len(current) + len(sentence) + 1 <= max_chars:
                    current += ("" if not current else " ") + sentence
                else:
                    if current:
                        chunks.append(current.strip())
                    current = sentence
        else:
            if len(current) + len(paragraph) + 1 <= max_chars:
                current += ("" if not current else "\n") + paragraph
            else:
                if current:
                    chunks.append(current.strip())
                current = paragraph

    if current.strip():
        chunks.append(current.strip())

    return [c for c in chunks if c]


def text_to_speech(
    script: str,
    episode: int,
    cfg: dict,
    openai_client,
    max_retries: int = 3,
) -> str:
    """Omvandlar manus till MP3 via OpenAI TTS, med chunkning för långa texter."""
    tts_cfg = cfg["openai_tts"]
    voice = tts_cfg["voices"][f"ep{episode}"]
    model = tts_cfg["model"]
    path = f"/tmp/podcast_ep{episode}.mp3"

    processed = preprocess_script(script)
    chunks = _split_chunks(processed)

    logger.info(
        "OpenAI TTS: %d tecken → %d chunk(s), röst %s, modell %s...",
        len(processed), len(chunks), voice, model,
    )

    audio_parts = []
    for i, chunk in enumerate(chunks):
        last_exc = None
        for attempt in range(max_retries):
            try:
                response = openai_client.audio.speech.create(
                    model=model,
                    voice=voice,
                    input=chunk,
                    response_format="mp3",
                )
                audio_parts.append(response.content)
                logger.info("Chunk %d/%d klar (%d tecken)", i + 1, len(chunks), len(chunk))
                break
            except Exception as e:
                last_exc = e
                wait = 2 ** attempt
                logger.warning(
                    "Chunk %d försök %d misslyckades: %s — väntar %ds",
                    i + 1, attempt + 1, e, wait,
                )
                time.sleep(wait)
        else:
            raise RuntimeError(
                f"OpenAI TTS misslyckades på chunk {i + 1} efter {max_retries} försök: {last_exc}"
            )

    # Slå ihop alla MP3-delar till en fil
    with open(path, "wb") as f:
        for part in audio_parts:
            f.write(part)

    logger.info("Ljud: %d KB (%d delar)", os.path.getsize(path) // 1024, len(audio_parts))
    return path
