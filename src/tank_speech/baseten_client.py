"""baseten_client.py — Baseten speech config + wire-shape hooks (stdlib only).

This module OPENs the Baseten path; it does not wire it to the tank.
Nothing here runs at import, nothing is sent anywhere until a caller
explicitly invokes a transport it injected itself, and no credential is
ever printed or returned (status() reports booleans, not values).

Why Baseten for speech (see DEVLOG 2026-10-28 platform split): duplex
voice lives or dies on streaming latency — streaming transcription,
streaming LLM tokens, streaming TTS — which is Baseten's optimised path.
The robot-side consequence is in session.py: all of it happens on a
background worker so the drive loop never waits on the network.

Configuration (environment only, never committed):

    BASETEN_API_KEY        Baseten API key (enables everything below)
    BASETEN_STT_MODEL_ID   deployed streaming-STT model id (Whisper/Qwen3-ASR)
    BASETEN_STT_CHAIN_ID   ...or a Chain id instead of a model id
    BASETEN_STT_WS_URL     ...or the full wss:// endpoint (wins over ids)
    BASETEN_TTS_MODEL_ID   deployed streaming-TTS model id (duplex replies)
    BASETEN_TTS_WS_URL     ...or its full wss:// endpoint
    BASETEN_LLM_MODEL      Model-API id for the parser fallback translator
    BASETEN_API_BASE       default https://inference.baseten.co/v1

Deploy the models first (Baseten Model Library -> Deploy Streaming for
Whisper Large V3 / Qwen3-ASR, a streaming TTS for replies), then set the
ids above. Until then every hook reports disabled and degrades to a
no-op — the tank keeps working on typed input exactly as today.
"""

import io
import json
import os
import time
import urllib.request
import wave
from dataclasses import dataclass
from typing import Optional

DEFAULT_API_BASE = "https://inference.baseten.co/v1"
# The one Model-API LLM verified working on Adam's Baseten account
# (2026-10-29, via the Pi). Used ONLY as the parser-fallback translator:
# it may propose a sentence that must re-classify as goto (session.py).
DEFAULT_LLM_MODEL = "meta-models/muse-spark-open-1026"


def build_model_ws_url(model_id: str) -> str:
    """Truss-style streaming endpoint for a deployed model id."""
    return (f"wss://model-{model_id}.api.baseten.co"
            f"/environments/production/websocket")


def build_chain_ws_url(chain_id: str) -> str:
    """Chain-style streaming endpoint (STT->LLM->TTS co-located)."""
    return (f"wss://chain-{chain_id}.api.baseten.co"
            f"/environments/production/websocket")


@dataclass
class SpeechConfig:
    api_key: str = ""
    stt_model_id: str = ""
    stt_chain_id: str = ""
    stt_endpoint: str = ""   # explicit BASETEN_STT_WS_URL, wins over ids
    tts_model_id: str = ""
    tts_endpoint: str = ""   # explicit BASETEN_TTS_WS_URL
    llm_model: str = ""
    api_base: str = DEFAULT_API_BASE

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        return cls(
            api_key=env.get("BASETEN_API_KEY", ""),
            stt_model_id=env.get("BASETEN_STT_MODEL_ID", ""),
            stt_chain_id=env.get("BASETEN_STT_CHAIN_ID", ""),
            stt_endpoint=env.get("BASETEN_STT_WS_URL", ""),
            tts_model_id=env.get("BASETEN_TTS_MODEL_ID", ""),
            tts_endpoint=env.get("BASETEN_TTS_WS_URL", ""),
            llm_model=env.get("BASETEN_LLM_MODEL", "") or DEFAULT_LLM_MODEL,
            api_base=env.get("BASETEN_API_BASE", DEFAULT_API_BASE),
        )

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)

    @property
    def stt_configured(self) -> bool:
        return bool(self.stt_endpoint or self.stt_model_id or self.stt_chain_id)

    @property
    def enabled(self) -> bool:
        """Speech can be attempted at all: key + at least an STT target."""
        return self.has_key and self.stt_configured

    def stt_ws_url(self) -> str:
        return self._resolve(self.stt_endpoint, self.stt_model_id,
                             self.stt_chain_id)

    def tts_ws_url(self) -> str:
        return self._resolve(self.tts_endpoint, self.tts_model_id, "")

    @staticmethod
    def _resolve(explicit, model_id, chain_id):
        if explicit:
            return explicit
        if model_id:
            return build_model_ws_url(model_id)
        if chain_id:
            return build_chain_ws_url(chain_id)
        return ""

    def status(self) -> dict:
        """Redacted status for /api/speech/status and CLI. No values."""
        return {
            "enabled": self.enabled,
            "has_key": self.has_key,
            "stt": ("configured" if self.stt_configured else "unconfigured"),
            "stt_ws_url": self.stt_ws_url() or None,
            "tts": ("configured" if (self.tts_endpoint or self.tts_model_id)
                    else "unconfigured"),
            "llm_fallback": ("configured" if (self.has_key and self.llm_model)
                             else "unconfigured"),
            "llm_model": self.llm_model if self.has_key else None,
            "api_base": self.api_base,
        }


@dataclass
class TranscriptEvent:
    text: str
    is_final: bool = False
    speaker: Optional[str] = None


def parse_transcript_event(raw) -> Optional[TranscriptEvent]:
    """Tolerant parser for streaming-transcription messages.

    Baseten streaming models differ in envelope shape; accept the common
    ones ({text|transcript, is_final|final}, {segments:[{text}]}, a bare
    JSON string, or a plain string). Garbage -> None, never an exception:
    a malformed packet must not kill the speech worker or the robot loop.
    """
    if isinstance(raw, (bytes, str)):
        if isinstance(raw, bytes):
            try:
                raw = raw.decode()
            except UnicodeDecodeError:
                return None
        try:
            raw = json.loads(raw)  # wire messages are JSON; garbage fails closed
        except ValueError:
            return None
        if isinstance(raw, str):
            raw = {"text": raw}
    if isinstance(raw, TranscriptEvent):
        return raw if raw.text.strip() else None
    if not isinstance(raw, dict):
        return None
    text = raw.get("text") or raw.get("transcript") or ""
    if not text and isinstance(raw.get("segments"), list):
        text = "".join(str(s.get("text", "")) for s in raw["segments"]
                        if isinstance(s, dict))
    text = str(text).strip()
    if not text:
        return None
    is_final = bool(raw.get("is_final", raw.get("final", False)))
    return TranscriptEvent(text=text, is_final=is_final,
                           speaker=raw.get("speaker"))


# ---------------------------------------------------------------------------
# Live transports — the one seam session.py was waiting for. Both are only
# constructed when the config says speech can be attempted; importing this
# module still sends nothing anywhere.
# ---------------------------------------------------------------------------

def wav_to_pcm(data: bytes) -> bytes:
    """Strip a RIFF/WAVE header down to raw samples; pass PCM through."""
    if not data or not data.startswith(b"RIFF"):
        return data
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            return w.readframes(w.getnframes())
    except (wave.Error, EOFError):
        return data


class BasetenStreamTranscriber:
    """transcribe_fn for SpeechSession: one utterance per call.

    Opens the deployed streaming-STT websocket, streams the utterance as
    binary PCM frames, sends a {"type": "end"} text frame, then collects
    transcript messages until a final arrives, the peer closes, or an
    idle timeout passes. Raw messages are returned for
    parse_transcript_event(); exceptions propagate to the worker, which
    records them in status()["last_error"] and keeps the robot loop alive.

    Protocol note: binary-audio-in / JSON-text-out is the Baseten Whisper
    Streaming shape (docs.baseten.co streaming transcription API). Qwen3-
    ASR streaming differs in its end/completion signals; if Adam deploys
    that instead, this class is the one place to adapt.
    """

    def __init__(self, config, connect=None, chunk_bytes=32000,
                 idle_timeout=4.0, total_timeout=30.0):
        if connect is None:
            from tank_speech.ws_client import ws_connect
            connect = ws_connect
        self._config = config
        self._connect = connect
        self._chunk_bytes = chunk_bytes
        self._idle_timeout = idle_timeout
        self._total_timeout = total_timeout

    def __call__(self, audio: bytes):
        pcm = wav_to_pcm(audio or b"")
        headers = {"Authorization": "Bearer " + self._config.api_key}
        ws = self._connect(self._config.stt_ws_url(), headers=headers,
                           timeout=self._total_timeout)
        events = []
        try:
            for i in range(0, len(pcm), self._chunk_bytes):
                ws.send_binary(pcm[i:i + self._chunk_bytes])
            ws.send_text(json.dumps({"type": "end"}))
            ws.settimeout(self._idle_timeout)
            deadline = time.monotonic() + self._total_timeout
            while time.monotonic() < deadline:
                try:
                    kind, payload = ws.recv_message()
                except TimeoutError:
                    break  # idle: no final is coming; keep what we have
                if kind == "close":
                    break
                if kind == "text":
                    events.append(payload)
                    ev = parse_transcript_event(payload)
                    if ev is not None and ev.is_final:
                        break
        finally:
            ws.close()
        return events


def make_transcribe_fn(config):
    """A SpeechSession transcribe_fn, or None when STT is unconfigured."""
    if not config.enabled:
        return None
    return BasetenStreamTranscriber(config)


class BasetenStreamConnection:
    """Stateful live stream to the deployed STT model (duplex leg one).

    open() connects once; send_audio() forwards PCM as it arrives;
    poll() drains whatever transcript messages are ready (short 50 ms
    blocking read, [] when idle); send_end() finishes the utterance.
    The phone-server relay owns one of these per browser socket. Same
    protocol note as BasetenStreamTranscriber: Whisper Streaming shape;
    Qwen3-ASR adapts here.
    """

    def __init__(self, config, connect=None):
        if connect is None:
            from tank_speech.ws_client import ws_connect
            connect = ws_connect
        self._config = config
        self._connect = connect
        self._ws = None

    def open(self):
        headers = {"Authorization": "Bearer " + self._config.api_key}
        self._ws = self._connect(self._config.stt_ws_url(),
                                 headers=headers, timeout=30.0)
        self._ws.settimeout(0.05)
        return self

    def send_audio(self, pcm: bytes):
        if self._ws is not None and pcm:
            self._ws.send_binary(bytes(pcm))

    def send_end(self):
        if self._ws is not None:
            self._ws.send_text(json.dumps({"type": "end"}))

    def poll(self):
        """Ready transcript messages (raw), or []. Never parks >50 ms."""
        events = []
        if self._ws is None:
            return events
        while True:
            try:
                kind, payload = self._ws.recv_message()
            except (TimeoutError, BlockingIOError):
                break
            if kind == "close":
                self.close()
                break
            if kind == "text":
                events.append(payload)
                continue
            break
        return events

    def close(self):
        if self._ws is not None:
            try:
                self._ws.close()
            finally:
                self._ws = None


_LLM_SYSTEM = (
    "You rewrite one spoken robot request as a single simple command. "
    "If the user wants the robot to go to or look at a thing, reply with "
    "exactly: go get the <thing>. Otherwise reply with exactly: UNKNOWN. "
    "Reply with only that, no other words.")


def make_llm_fn(config, opener=None):
    """Parser-fallback translator via Baseten Model APIs (chat completions).

    Returns fn(text) -> proposal string, or None when no key is set. The
    proposal is worthless until session.llm_fallback_route re-classifies
    it as goto — this function alone can never produce a command.
    """
    if not config.has_key or not config.llm_model:
        return None
    opener = opener or urllib.request.urlopen
    url = config.api_base.rstrip("/") + "/chat/completions"

    def llm_fn(text):
        body = json.dumps({
            "model": config.llm_model,
            "messages": [{"role": "system", "content": _LLM_SYSTEM},
                         {"role": "user", "content": str(text)}],
            # Muse Spark is a reasoning model: most of the budget goes
            # to reasoning_content before `content` appears. 300 tokens
            # measured flaky (291 used, content sometimes empty); 800
            # leaves the one-line answer room to land.
            "max_tokens": 800, "temperature": 0,
        }).encode()
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + config.api_key})
        with opener(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"].get("content") or ""
        return content.strip() or None

    return llm_fn
