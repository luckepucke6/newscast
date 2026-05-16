"""Text-to-speech via OpenAI TTS."""
import logging
import os
import time

from script import preprocess_script

logger = logging.getLogger(__name__)


def text_to_speech(
    script: str,
    episode: int,
    cfg: dict,
    openai_client,
    max_retries: int = 3,
) -> str:
    """Omvandlar manus till MP3 via OpenAI TTS."""
    tts_cfg = cfg["openai_tts"]
    voice = tts_cfg["voices"][f"ep{episode}"]
    model = tts_cfg["model"]
    path = f"/tmp/podcast_ep{episode}.mp3"

    processed = preprocess_script(script)
    logger.info("OpenAI TTS: %d tecken, röst %s, modell %s...", len(processed), voice, model)

    last_exc = None
    for attempt in range(max_retries):
        try:
            response = openai_client.audio.speech.create(
                model=model,
                voice=voice,
                input=processed,
                response_format="mp3",
            )
            response.stream_to_file(path)
            logger.info("Ljud: %d KB", os.path.getsize(path) // 1024)
            return path
        except Exception as e:
            last_exc = e
            wait = 2 ** attempt
            logger.warning("text_to_speech försök %d misslyckades: %s — väntar %ds", attempt + 1, e, wait)
            time.sleep(wait)
    raise RuntimeError(f"OpenAI TTS misslyckades efter {max_retries} försök: {last_exc}")
