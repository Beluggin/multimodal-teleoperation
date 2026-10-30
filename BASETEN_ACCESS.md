# Baseten access from isolated Muse

Enabled 2026-10-30. Exit and restart `muse` to load the broker policy and
MCP settings. Existing isolated tank sessions can be resumed.

## Configuration and scope

The isolated profile has `baseten` at https://api.baseten.co/mcp and
`baseten_docs` at https://docs.baseten.co/mcp using native streamable HTTP.
The backend uses the existing project Baseten API key, copied into the private
isolated settings file (0600), outside the repo. Rotate that copy when rotating
the project key. It carries the key's existing account permissions.
No approval settings were changed.

Broker HTTPS port 443 destinations: `api.baseten.co`, `docs.baseten.co`,
`inference.baseten.co`, and `model-<id>.api.baseten.co` /
`chain-<id>.api.baseten.co` deployment hosts. Public-IP checks still apply.
Other Baseten subdomains, generic storage hosts and non-443 ports remain
blocked. The existing Meta/Modal/tank exceptions are unchanged.

Official backend setup: https://www.baseten.co/resources/changelog/connect-coding-agents-to-baseten/

## Verified checks

From the actual Bubblewrap sandbox, authenticated MCP initialization and
paginated tool discovery succeeded: 161 backend tools, including
`deploy_model_from_library`, and 3 documentation tools. Muse's echo startup
accepted the settings. Policy regression tests (3) and real namespace checks
passed: host home and credentials remain hidden, direct networking fails,
and disallowed proxy destinations fail closed.

Host commands to repeat these checks:

```bash
python3 ~/.local/lib/muse-tank-isolation/test_policy.py
muse --isolation-check python3 /isolation/check_inside.py
muse --isolation-check python3 /isolation/check_baseten.py
```

These checks do not create deployments, run inference, or move the tank.
Backend tool discovery does not prove every tool is accepted by Muse.
Muse reports `create_sandbox` skipped for credential-shaped schema text.
Its upstream schema includes a dummy `sk-proj-demo-not-a-valid-api-key`
example, a likely false-positive trigger. This tool creates remote compute
sandboxes; model-library deployment uses `deploy_model_from_library` instead.
The schema filter remains enabled. No key was printed by the checks.

## Whisper next step

Use the model-library tools to locate the streaming Whisper listing, confirm
its hardware/billing settings, deploy it, and wait for ACTIVE. Set
`BASETEN_STT_MODEL_ID` in the runtime environment and follow
`tank_speech/README.md` for the Pi speech relay and HTTPS microphone setup.
Whisper deployment, live transcription, and duplex playback were not tested
as part of this access change. Whisper billing is separate from Muse model
credits. No GPU deployment was created by these checks.

## Rollback

Exit Muse. Pre-change host policy/checks and isolated settings are backed up
privately at `~/.local/state/muse-tank-isolation/before-baseten-2026-10-30/`.
Restore the three Python files to `~/.local/lib/muse-tank-isolation/`, and
remove only `baseten` / `baseten_docs` from isolated settings (or restore the
settings backup if no subsequent settings edits need preserving). Restart
Muse. Keep backup settings private; they may contain credentials.
