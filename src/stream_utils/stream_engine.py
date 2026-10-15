import io
import wave
import logging
import numpy as np
from fastrtc import (
    AdditionalOutputs,
    AlgoOptions,
    ReplyOnPause,
    SileroVadOptions,
    Stream,
)
from groq import AsyncGroq
from src.stream_utils.turn_creds import get_turn_creds
from src.secrets import groq_key

logger = logging.getLogger(__name__)

STT_MODEL = "whisper-large-v3-turbo"
LLM_MODEL = "openai/gpt-oss-20b"
LANGUAGE = "en"

RECAST_SYSTEM_PROMPT = """You are a recast engine for language learners.  
Rewrite the learner's sentence the way a fluent native speaker would  
naturally say it: fix grammar, word choice, collocations, and tense.  
Preserve their meaning, intent, and level of formality.  
Do NOT answer the sentence, add new information, or explain anything.  
If the sentence is already natural, return it unchanged.  
Output ONLY the rewritten sentence — no quotes, no notes, no explanations."""

groq_client = AsyncGroq(api_key=groq_key)


def _audio_to_wav_bytes(audio: tuple[int, np.ndarray]):
    sr, data = audio
    pcm = np.asarray(data).reshape(-1)
    if np.issubdtype(pcm.dtype, np.floating):
        pcm = (np.clip(pcm, -1.0, 1.0) * 32767).astype(np.int16)
    elif pcm.dtype != np.int16:
        pcm = pcm.astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


async def _stt(wav_bytes: bytes):
    result = await groq_client.audio.transcriptions.create(
        model=STT_MODEL,
        file=("utt.wav", io.BytesIO(wav_bytes)),
        language=LANGUAGE,
        response_format="text",
    )
    return result if isinstance(result, str) else getattr(result, "text", "")


async def _recast(text: str):
    chat = await groq_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": RECAST_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0.2,
        max_tokens=150,
    )
    return (chat.choices[0].message.content or "").strip().strip('"')


async def recast_fn(audio: tuple[int, np.ndarray]):
    try:
        you = await _stt(_audio_to_wav_bytes(audio))
        if not you.strip():
            return

        native = await _recast(you.strip())
        yield AdditionalOutputs({"you": you.strip(), "native": native})

    except Exception:
        logger.exception("recast pipeline failed")


async def refresh_server_rtc_config():
    creds = await get_turn_creds(ttl=3600)
    stream.server_rtc_configuration = stream.convert_to_aiortc_format(creds)


stream = Stream(
    handler=ReplyOnPause(
        recast_fn,
        algo_options=AlgoOptions(
            audio_chunk_duration=0.5,
            started_talking_threshold=0.2,
            speech_threshold=0.1,
        ),
        model_options=SileroVadOptions(
            threshold=0.5,
            min_speech_duration_ms=250,
            min_silence_duration_ms=600,
            max_speech_duration_s=15,
            speech_pad_ms=400,
        ),
    ),
    modality="audio",
    mode="send",
)
