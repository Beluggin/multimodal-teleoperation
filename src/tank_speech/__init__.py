"""tank_speech — Baseten speech hooks for the tank. NOT wired to hardware.

Public surface (all safe to call with nothing configured):

    cfg = SpeechConfig.from_env()          # disabled until a key + model exist
    sess = SpeechSession(cfg, transcribe_fn=None)
    sess.start()                           # background worker; never blocks caller
    sess.feed_audio(chunk)                 # -> False when disabled/full
    action = sess.tick()                   # -> routed dict or None, non-blocking

Routing reuses tank_tools' fixed-phrase parser only. A routed dict is a
preview (same shape as tank_phone /api/text): nothing here sends a motor
or servo command, ever. See README.md for the Baseten setup steps.
"""

from tank_speech.baseten_client import (  # noqa: F401
    SpeechConfig, TranscriptEvent, build_chain_ws_url, build_model_ws_url,
    parse_transcript_event,
)
from tank_speech.session import (  # noqa: F401
    SpeechInbox, SpeechSession, llm_fallback_route, route_transcript,
)
