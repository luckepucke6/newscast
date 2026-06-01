"""Text-to-speech via Azure Cognitive Services Speech."""
import logging
import os
import time

import azure.cognitiveservices.speech as speechsdk

from script import preprocess_script

logger = logging.getLogger(__name__)

MAX_CHARS = 5000


def _split_chunks(text: str, max_chars: int = MAX_CHARS) -> list:
    """Delar upp text i bitar på max max_chars tecken vid stycke- eller meningsgränser."""
    chunks = []
    current = ""

    for paragraph in text.split("\n"):
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
    max_retries: int = 3,
) -> str:
    """Omvandlar manus till MP3 via Azure Speech, med chunkning för långa texter."""
    tts_cfg = cfg["azure_tts"]
    voice = tts_cfg["voices"][f"ep{episode}"]
    region = tts_cfg["region"]
    key = os.environ["AZURE_SPEECH_KEY"]
    path = f"/tmp/podcast_ep{episode}.mp3"

    speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio24Khz96KBitRateMonoMp3
    )
    speech_config.speech_synthesis_voice_name = voice

    processed = preprocess_script(script)
    chunks = _split_chunks(processed)

    logger.info(
        "Azure TTS: %d tecken → %d chunk(s), röst %s...",
        len(processed), len(chunks), voice,
    )

    audio_parts = []
    for i, chunk in enumerate(chunks):
        last_exc = None
        for attempt in range(max_retries):
            try:
                synthesizer = speechsdk.SpeechSynthesizer(
                    speech_config=speech_config, audio_config=None
                )
                result = synthesizer.speak_text_async(chunk).get()
                if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                    audio_parts.append(result.audio_data)
                    logger.info("Chunk %d/%d klar (%d tecken)", i + 1, len(chunks), len(chunk))
                    break
                else:
                    raise RuntimeError(f"Azure TTS misslyckades: {result.reason}, {result.cancellation_details.error_details if result.reason == speechsdk.ResultReason.Canceled else ''}")
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
                f"Azure TTS misslyckades på chunk {i + 1} efter {max_retries} försök: {last_exc}"
            )

    with open(path, "wb") as f:
        for part in audio_parts:
            f.write(part)

    logger.info("Ljud: %d KB (%d delar)", os.path.getsize(path) // 1024, len(audio_parts))
    return path
