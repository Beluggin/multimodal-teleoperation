# tank_vision — YOLO + SAM for the tank (no GUI yet)

Callable module + CLI. The phone GUI will call exactly these functions;
this stage only proves they work, first on the desktop, then on the Pi.

## Contract

All coordinates normalized 0..1, origin top-left (same as `tank_phone` taps).

| Call | Meaning | Phone gesture later |
|---|---|---|
| `detect(image)` | YOLO boxes only → `list[Detection]` | — |
| `detect_and_segment(image)` | every YOLO box → SAM mask | auto mode |
| `focus(image, box)` | best known object inside the box, else SAM on the box itself | **drag: "go check that out"** |
| `focus_point(image, x, y)` | `focus()` in a small box around a tap | **tap** |
| `mask_from_point/box(...)` | raw SAM prompts | (advanced/debug) |
| `aim(segmented)` | `{dx_right, dy_up, area_frac}` vs frame centre, or `None` | aim error for pan/tilt/drive |

`Segmented.summary()` → `{source, label, confidence, mask_box, centroid,
area_frac}` (all normalized). Empty mask → `{"empty": true}` and
`aim() is None`: no target. Callers must never treat that as "drive
straight" — same no-motion-on-unknown rule as the text parser.

Models: one dependency, Ultralytics — `yolo11n.pt` (detector) +
`mobile_sam.pt` (segmenter, Meta SAM distilled). Smallest pair expected to
run live on the Pi's CPU. If mask quality on `mc.jpg` disappoints, the step
up is SAM2-tiny (`sam2_t.pt`) behind the same adapters. Weights download
on first use into `tank_vision/weights/` (override with `TANK_VISION_HOME`).

Note: pretrained YOLO knows COCO everyday objects. On `mc.jpg` (a circuit
board close-up) expect `objects: []` from the auto path — a correct empty
result, not a failure. The tap/drag focus path is the one to judge there:
SAM segments whatever you point at, known class or not.

## Desktop proof (run in a regular terminal, outside Muse's sandbox)

The sandbox cannot reach PyPI; your desktop terminal can. The environment
belongs to the project:

```bash
cd ~/multimodal-teleoperation
python3 -m venv .venv
.venv/bin/pip install ultralytics        # pulls CPU torch, ~2 GB
.venv/bin/python -m tank_vision mc.jpg   # auto path (expect [] on mc.jpg)
.venv/bin/python -m tank_vision mc.jpg --point 0.335,0.320        # a capacitor
.venv/bin/python -m tank_vision mc.jpg --focus 0.11,0.60,0.31,0.81 # L298 chip
```

Outputs land in `vision_out/` (`*_result.json`, `*_overlay.png`,
`*_mask_N.png`). For the auto path, also run any ordinary photo with
everyday objects (chair, cup, person…) — that is where YOLO boxes appear.

## Tests (no torch needed)

```bash
python3 -m unittest discover -s tank_vision -p 'test_*.py'   # 8 plumbing tests
python3 -m unittest discover -s tank_tools -p 'test_*.py'    # parser, unchanged
```

## SAM 3.1 (flagship path, Meta Model API)

`tank_vision/meta_sam.py` calls SAM 3.1 where the hackathon serves it:
the Meta Model API (`api.meta.ai`, model `sam-3.1`, text prompt + image,
boxes + masks out, metered against the hackathon Model API credits).
No HF gate, no GPU. Key from `MODEL_API_KEY` env only — never commit it.

    MODEL_API_KEY=... python3 -m tank_vision.meta_sam mc.jpg "silver capacitor"
    MODEL_API_KEY=... python3 -m tank_vision.meta_sam --probe mc.jpg "red cup"

`--probe` saves the raw response (mask encoding gets confirmed against
one real response before downstream geometry is trusted).


## Pi (after the desktop proof passes)

Pi has internet + `uv`. Same module, ARM CPU wheels:

```bash
ssh tank
uv venv --python 3.11 ~/tank_vision_env
uv pip install --python ~/tank_vision_env/bin/python ultralytics
uv pip uninstall --python ~/tank_vision_env/bin/python opencv-python
uv pip install --python ~/tank_vision_env/bin/python opencv-python-headless
# copy tank_vision/ (incl. weights/) to ~/tank_vision, run the same CLI
```

The opencv swap is required: stock `opencv-python` needs `libGL.so.1`,
which the headless Pi lacks; the headless build provides the same `cv2`.
Measured on the Pi (640x480, cold, incl. model load): ~18 s auto,
~9 s point prompt. That is tap-to-investigate pace, not video rate —
design the GUI around still-frame focus, not live tracking.
Nothing in this package moves hardware.
