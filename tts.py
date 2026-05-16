"""Text-to-speech via ElevenLabs Flash v2.5."""
import logging
import os
import time

from script import preprocess_script

logger = logging.getLogger(__name__)


def text_to_speech(
    script: str,
    episode: int,
    cfg: dict,
    eleven_client,
    max_retries: int = 3,
) -> str:
    """Omvandlar manus till MP3 via ElevenLabs Flash v2.5."""
    voice_id = cfg["voices"][f"ep{episode}"]
    model_id = cfg["elevenlabs"]["model"]
    path = f"/tmp/podcast_ep{episode}.mp3"

    logger.info("ElevenLabs Flash: %d tecken, röst %s...", len(script), voice_id)

    last_exc = None
    for attempt in range(max_retries):
        try:
            audio_stream = eleven_client.text_to_speech.convert(
                voice_id=voice_id,
                text=preprocess_script(script),
                model_id=model_id,
                language_code="sv",
                output_format="mp3_44100_128",
            )
            with open(path, "wb") as f:
                for chunk in audio_stream:
                    f.write(chunk)
            logger.info("Ljud: %d KB", os.path.getsize(path) // 1024)
            return path
        except Exception as e:
            last_exc = e
            wait = 2 ** attempt
            logger.warning("text_to_speech försök %d misslyckades: %s — väntar %ds", attempt + 1, e, wait)
            time.sleep(wait)
    raise RuntimeError(f"ElevenLabs TTS misslyckades efter {max_retries} försök: {last_exc}")
