"""Text-to-speech via Azure Cognitive Services (Neural TTS)."""
import logging
import os
import time

import requests

from script import preprocess_script

logger = logging.getLogger(__name__)

AZURE_TTS_URL = "https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"

SSML_TEMPLATE = """\
<speak version='1.0' xml:lang='sv-SE'>
  <voice xml:lang='sv-SE' name='{voice}'>
    {text}
  </voice>
</speak>"""


def text_to_speech(
    script: str,
    episode: int,
    cfg: dict,
    max_retries: int = 3,
) -> str:
    """Omvandlar manus till MP3 via Azure Neural TTS."""
    voice = cfg["azure_tts"]["voices"][f"ep{episode}"]
    region = os.environ["AZURE_SPEECH_REGION"]
    key = os.environ["AZURE_SPEECH_KEY"]
    path = f"/tmp/podcast_ep{episode}.mp3"

    processed = preprocess_script(script)
    ssml = SSML_TEMPLATE.format(voice=voice, text=processed)
    url = AZURE_TTS_URL.format(region=region)

    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-48khz-192kbitrate-mono-mp3",
        "User-Agent": "newscast",
    }

    logger.info("Azure TTS: %d tecken, röst %s...", len(processed), voice)

    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, headers=headers, data=ssml.encode("utf-8"), timeout=120)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            with open(path, "wb") as f:
                f.write(resp.content)
            logger.info("Ljud: %d KB", os.path.getsize(path) // 1024)
            return path
        except Exception as e:
            last_exc = e
            wait = 2 ** attempt
            logger.warning("text_to_speech försök %d misslyckades: %s — väntar %ds", attempt + 1, e, wait)
            time.sleep(wait)
    raise RuntimeError(f"Azure TTS misslyckades efter {max_retries} försök: {last_exc}")
