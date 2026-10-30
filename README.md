# multimodal-teleoperation

Meta hackathon entry: words become actions on a XiaoR Geek tank.
Natural-language target → Meta model interprets and finds it → tank moves
in short bounded steps → stops at the target.

Status: standalone tank utilities imported; multimodal demo integration remains
to be built. The intended safety posture is no movement for unknown, negated
or ambiguous input, with stop taking priority. Existing decimal-duration and
stop-priority bugs remain; the passing baseline tests do not cover them.

No tokens or keys in this repo, ever.

## Muse and SSH

On Adam's desktop, run `muse` normally. The launcher always opens this repo
as `/workspace` inside the tank-only sandbox, regardless of the host working
directory. Use a fresh session; original sessions are outside this profile.
The wrapper disables Muse's inner shell sandbox because it hides the SSH
broker. The outer OS sandbox still encloses Muse and every tool; approval
controls remain enabled. A built-in-sandbox warning refers to that inner layer.
Start with `tank_tools/MUSE_BRIEF.md` to continue the servo work.

Inside Muse, `ssh tank` reaches `pi@<tailscale-ip>`; `ssh tank-lan` reaches
`pi@tank.local`. SCP uses the same SSH configuration. The dedicated key
is outside the repo. Physical movement still requires Adam's authorization.
SSH exposes whatever that account can read on the Pi; do not place unrelated
private material there. Direct desktop services and other network targets
are unavailable. Other permitted destinations are Meta API/login HTTPS and
Modal's HTTPS services plus three verified Modal storage/CDN hosts, and
Baseten's API/docs/inference and model/chain deployment HTTPS endpoints.
See [Baseten MCP access](BASETEN_ACCESS.md) for configuration and checks.
Missing access fails closed; there is no automatic unrestricted retry.

## Modal access (2026-10-27)

Exit and restart `muse` once to load the updated broker. Existing tank-only
sessions can be resumed in this isolated profile. Inside Muse, use `modal`
or `.venv/bin/python -m modal`:

```bash
modal --version
modal run modal_app.py --image mc.jpg --point 0.335,0.320
```

The second command starts the existing GPU app and consumes Modal credits;
it is a usage example, not part of the isolation checks. The launcher exposes
only the active Modal login in its separate home, outside this repo. Siggy's
files, host credentials and direct desktop networking remain hidden.

Modal 1.6.3's proxy extras are installed in the existing project venv. The
`modal` wrapper handles the venv's host-specific executable path. Model/image
dependency downloads happen on Modal; this exception does not grant the
desktop unrestricted Internet access. See [Modal access details](MODAL_ACCESS.md)
for destinations, checks and rollback.

The agent's history is separate, but anything deliberately put in this repo,
read on the tank, pasted into Muse, or sent in an API request can reach Meta.
This boundary does not reverse earlier uploads or certify future paid terms.

## Local controls and checks

### Agent round table

From a host terminal, run `python3 ~/multimodal-teleoperation/round_table.py`.
Claude and Codex advise; Muse can implement inside its existing tank-only
isolation. The directory name is singular. Example:

```text
@all Suggest a bounded fix for target loss in tank_vision/drive_run.py
/share 2
@muse Review the shared advice against the current implementation
/keys muse
@muse Implement the agreed fix and run offline tests; no physical tests
/take
```

Use the actual displayed adviser answer ID with `/share`. Only selected
answers, direct `@muse` prompts, and Muse's own replies enter Muse's room
context. Adviser questions and unshared answers are withheld. Review an
answer for unrelated/private material before sharing it. `@all` addresses
the two advisers; `/help` lists commands. No automatic agent handoffs occur.

The controller never resumes existing conversations or saves a transcript;
each CLI may retain its own logs. Claude runs with tools disabled and safe
mode; Codex uses fresh ephemeral read-only sessions with user config ignored.
These adviser settings are not Muse's OS isolation. Muse always uses the
existing host supervisor with its pinned workspace, private profile, broker,
and contributor settings unchanged; missing isolation fails closed. Default
Muse discussion disables shell and filesystem writes; `/keys muse` restores
its normal tool approvals. No permission to move hardware follows from keys.
Already-shared content cannot be recalled; quit for a fresh room.

Offline adapter checks: `python3 -m unittest test_round_table`.
Live model compatibility/authentication must be checked at first use; the
offline suite does not exercise hosted providers.

Run the keyboard driver from a regular desktop terminal (outside Muse):

```bash
cd ~/multimodal-teleoperation
TANK_HOST=<tailscale-ip> python3 tank_tools/tank_control.py
```

It still uses the existing bench listener on port 5098, the existing
`/tmp/claude-1000/bench_token`, and `/tmp/claude-1000/tank_live.log`.
WASD/arrows drive, Space stops, `t` enters typed-command mode, `q` quits.
The token/log directory must exist as in the original setup. Live driving
was not exercised during the isolation setup.

```bash
python3 -m unittest discover -s tank_tools -p 'test_*.py'
```

`tank_bench/README.md` contains the measured motor map and listener setup.
The stock servo binary, about.py and JPEG are together in `xiaor/`.
IMPORT_MANIFEST.json records the initial copied-file hashes; later edits
should be logged in DEVLOG.md, not silently synchronized to the source project.
