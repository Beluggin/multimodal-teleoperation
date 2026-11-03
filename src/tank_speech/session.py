"""session.py — non-blocking speech session: the minimal-downtime half.

The robot should be doing something as close to all the time as possible,
so speech NEVER sits in the drive loop's critical path:

    drive/vision loop (main thread)          speech worker (background)
    -------------------------------          --------------------------
    sess.feed_audio(chunk)  --bounded queue->  transcribe_fn(chunk)
    action = sess.tick()    <-routed finals--  parse -> route -> inbox
    ... keeps driving either way ...

tick() polls with timeout=0: it returns a routed command preview or None
immediately, however slow the network is. Warmup (when a warmup_fn is
injected) also runs on the worker, so a cold Baseten replica warms while
the tank is already doing something else — not when the first command
arrives. Stop/estop finals jump the inbox queue ahead of older finals.

Safety: routing is tank_tools.classify() ONLY. Finals are routed, partials
never are. Unknown/refused/ambiguous/goto carry no motor commands (the
parser guarantees it). Nothing here calls run(), the bench listener, or
any servo path: a routed dict is a preview for a future authorised
caller to consume, exactly like tank_phone's /api/text.
"""

import os
import sys
import threading
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tank_tools"))

try:
    import xiaor_text_action as _xta
except ImportError:  # pragma: no cover - parser is in-repo; degrade honestly
    _xta = None

from tank_speech.baseten_client import SpeechConfig, parse_transcript_event  # noqa: E402

_PRIORITY_KINDS = {"stop", "estop"}


def route_transcript(text):
    """Final transcript -> preview dict via the fixed-phrase parser only."""
    if _xta is None:
        return {"kind": "unknown", "label": "unknown", "target": "",
                "commands": [], "reason": "parser unavailable",
                "priority": False, "source": "speech"}
    a = _xta.classify(text or "")
    return {"kind": a.kind, "label": a.label, "target": a.target,
            "commands": a.commands, "reason": a.reason,
            "priority": a.kind in _PRIORITY_KINDS, "source": "speech",
            "text": text or ""}


def llm_fallback_route(text, llm_fn=None):
    """Optional Baseten-LLM translator hook for parser-unknown speech.

    The LLM may only PROPOSE a cleaner sentence; the proposal is re-run
    through classify() and accepted only as a goto target. It can never
    create drive/arm commands, and with no llm_fn injected it is a no-op.
    Returns a routed dict or None.
    """
    base = route_transcript(text)
    if base["kind"] != "unknown" or llm_fn is None:
        return base if base["kind"] != "unknown" else None
    try:
        proposal = llm_fn(text)
    except Exception:
        return None
    if not proposal:
        return None
    routed = route_transcript(str(proposal))
    return routed if routed["kind"] == "goto" else None


class SpeechInbox:
    """Bounded routed-final queue. Partials are stored, never queued."""

    def __init__(self, maxsize=8):
        self.maxsize = maxsize
        self._priority = deque()
        self._normal = deque()
        self._lock = threading.Lock()
        self.latest_partial = ""

    def put_partial(self, text):
        with self._lock:
            self.latest_partial = text or ""

    def put_final(self, routed):
        with self._lock:
            lane = self._priority if routed.get("priority") else self._normal
            if len(self._priority) + len(self._normal) >= self.maxsize:
                if self._normal:      # drop oldest non-priority first
                    self._normal.popleft()
                elif lane is self._normal:
                    return            # full of priority items: drop new
                else:
                    self._priority.popleft()
            lane.append(routed)

    def poll(self):
        """Next routed final (priority first), or None. Never blocks."""
        with self._lock:
            if self._priority:
                return self._priority.popleft()
            if self._normal:
                return self._normal.popleft()
            return None

    def pending(self):
        with self._lock:
            return len(self._priority) + len(self._normal)


class SpeechSession:
    """Background transcription worker + non-blocking tick() for callers.

    transcribe_fn(chunk: bytes) -> raw event | list of raw events | str.
    It is the ONLY transport seam: wire it to a Baseten websocket client
    later (see README); tests inject fakes. Without it the session is
    disabled and feed_audio/tick are harmless no-ops.
    """

    def __init__(self, config=None, transcribe_fn=None, warmup_fn=None,
                 inbox=None, llm_fn=None):
        self.config = config or SpeechConfig.from_env()
        self._transcribe_fn = transcribe_fn
        self._warmup_fn = warmup_fn
        self._llm_fn = llm_fn
        self.inbox = inbox or SpeechInbox()
        self._audio = deque()
        self._audio_cv = threading.Condition()
        self._thread = None
        self._stopped = threading.Event()
        self.ready = threading.Event()
        self.last_error = ""

    @property
    def enabled(self):
        return self._transcribe_fn is not None

    def start(self):
        if self._thread is not None:
            return self
        self._stopped.clear()
        self._thread = threading.Thread(target=self._work, daemon=True,
                                        name="tank-speech")
        self._thread.start()
        return self

    def stop(self):
        self._stopped.set()
        with self._audio_cv:
            self._audio_cv.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def feed_audio(self, chunk) -> bool:
        """Queue one audio chunk. False (dropped) when disabled/full."""
        if not self.enabled or not chunk:
            return False
        with self._audio_cv:
            if len(self._audio) >= 32:   # bounded: drop, never block caller
                return False
            self._audio.append(chunk)
            self._audio_cv.notify()
            return True

    def tick(self):
        """Poll for one routed final. Timeout=0: the caller's loop owns time."""
        return self.inbox.poll()

    def status(self):
        return {"enabled": self.enabled, "ready": self.ready.is_set(),
                "last_error": self.last_error,
                "pending": self.inbox.pending(),
                "latest_partial": self.inbox.latest_partial,
                "config": self.config.status()}

    def _route_final(self, text):
        """Parser first; the optional LLM may only rescue an unknown into
        a goto (llm_fallback_route re-classifies and refuses the rest)."""
        routed = route_transcript(text)
        if routed["kind"] == "unknown" and self._llm_fn is not None:
            rescued = llm_fallback_route(text, llm_fn=self._llm_fn)
            if rescued is not None:
                return rescued
        return routed

    # -- worker ---------------------------------------------------------
    def _work(self):
        if self._warmup_fn is not None:
            try:
                self._warmup_fn()     # cold-start cost paid here, in parallel
            except Exception as e:    # warmup failure must not kill speech
                self.last_error = f"warmup: {e}"
        self.ready.set()
        while not self._stopped.is_set():
            with self._audio_cv:
                if not self._audio:
                    self._audio_cv.wait(timeout=0.2)
                if not self._audio:
                    continue
                chunk = self._audio.popleft()
            try:
                raw = self._transcribe_fn(chunk)
            except Exception as e:    # surface it; worker and robot survive
                self.last_error = str(e)
                continue
            for item in (raw if isinstance(raw, list) else [raw]):
                ev = parse_transcript_event(item)
                if ev is None:
                    continue
                if ev.is_final:
                    self.inbox.put_final(self._route_final(ev.text))
                else:
                    self.inbox.put_partial(ev.text)
