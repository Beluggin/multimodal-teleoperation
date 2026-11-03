# tank_speech — Baseten speech (wired 2026-10-29, preview-only)

Baseten is the duplex-speech platform for this demo (streaming STT →
LLM → TTS; see DEVLOG 2026-10-28). The phone path is now wired end to
end: phone mic → `POST /api/speech/audio` → background STT worker →
fixed-phrase parser → preview on the page. Nothing here can move the
tank: routed results are previews, exactly like typed Showcase input.
No Baseten call is made at import; transcription only happens when a
caller feeds audio to a configured session.

## Layout

- `baseten_client.py` — `SpeechConfig` (env-only, redacted `status()`),
  streaming-endpoint URL builders, tolerant `parse_transcript_event()`,
  plus the live transports: `BasetenStreamTranscriber` (the
  `transcribe_fn` seam: binary PCM frames in, JSON transcripts out,
  `{"type": "end"}` to finish an utterance) and `make_llm_fn()`
  (Model-API chat completions for the parser-fallback translator;
  default model `meta-models/muse-spark-open-1026`, the one verified
  on Adam's account — it is a reasoning model, hence max_tokens 800).
- `ws_client.py` — minimal stdlib WebSocket client (RFC 6455). The
  stdlib has none and this stack deploys stdlib-only to the Pi.
- `session.py` — `SpeechSession` background worker + `SpeechInbox`.
  `feed_audio()` queues bounded audio; `tick()` polls timeout=0 for a
  routed final. `route_transcript()` is `tank_tools.classify()` only;
  with an `llm_fn` injected, an unknown final may be rescued by
  `llm_fallback_route()` — the LLM proposes a sentence that must
  re-classify as `goto` (target only, never drive commands).
- `__main__.py` — `cd src && python3 -m tank_speech --status | --route "…"`.

## Minimal-downtime design

Speech work must never stall the thing the robot is already doing:

1. Transcription runs on one daemon worker thread. The drive/vision
   loop only calls `tick()` (non-blocking) and keeps driving either way.
2. Warmup runs on that worker at `start()`. A cold Baseten replica warms
   while the tank centres/drives on typed or vision input, not when the
   first voice command arrives. Check `sess.ready` / `status()`.
3. Queues are bounded and drop instead of blocking the caller.
   Partials update `latest_partial` only; only finals are routed.
4. Stop/estop finals jump ahead of queued finals in the inbox.
5. Worker errors land in `status()["last_error"]`; the session and the
   robot loop survive them.

## Going live (Adam's steps, in order)

2026-10-30: isolated Muse now has Baseten deployment/docs MCP access; see
[access and checks](../BASETEN_ACCESS.md). Restart Muse before using it.
No Whisper deployment or live audio test was performed during access setup.

> Route change (2026-10-29): the $100 Baseten credits are tied to
> "[HACKATHON] Muse Spark Open" (text+image in, token-priced), so
> Whisper can NOT spend them, and Muse Spark cannot hear audio.
> Primary STT is now the phone browser's `SpeechRecognition`
> (page → `/api/speech/transcript`, zero Baseten spend); the steps
> below remain only as the optional Baseten-STT upgrade path.

1. In Baseten: deploy a streaming STT model (Model Library: Whisper
   Large V3 Streaming → Deploy Streaming; Qwen3-ASR streaming uses a
   different end/completion protocol — if that one is chosen,
   `BasetenStreamTranscriber` is the one class to adapt). Note its id.
   This bills GPU time to account balance, NOT the Muse credits.
   As of 2026-10-29 the account has no deployments and no STT in the
   Model-API list.
2. Set env (never commit; `.env` is gitignored): `BASETEN_API_KEY`
   (done), `BASETEN_STT_MODEL_ID` (or `BASETEN_STT_CHAIN_ID` /
   `BASETEN_STT_WS_URL`). `BASETEN_LLM_MODEL` defaults to the verified
   Muse Spark id. STT bills GPU time separately from Muse model credits —
   side path only; demo inference stays on Meta models.
3. `cd src && python3 -m tank_speech --status` should report `enabled: true`.
4. Restart the Pi phone server with that env (safe flags of your
   choice; speech needs neither `--enable-servo` nor `--enable-motors`).
   The page's Hold-to-talk button enables when status says wired.
   Note: phone browsers only allow mic capture on HTTPS or localhost
   — on plain LAN HTTP the page says so and typed input still works.
5. Only with Adam present + per-case authorisation, consume `tick()`
   results in a drive loop. Stop must bypass any queue in that
   consumer, as it does in the parser today.

## Phone hooks

`src/tank_phone/server.py` exposes `GET /api/speech/status` (`wired` true
only with a live session), `POST /api/speech/transcript {"text"}`, and
`POST /api/speech/audio` (raw WAV, bounded, classify-only preview).

## Tests

`python3 -m unittest discover -s tests/tank_speech -p 'test_*.py'` — offline:
config redaction, URL builders, transcript shapes, parser-only routing,
LLM-fallback gating, inbox priority, a measured non-blocking check
(the caller loop ticks >10× while a fake transcriber is parked), the
WebSocket client + transcriber against a local fake Baseten server,
WAV stripping, and the LLM transport against a fake opener. Live
Baseten behaviour was verified separately from the Pi (DEVLOG).
