#!/usr/bin/env python3
"""CLI proof harness for tank_vision — no GUI, no hardware.

    .venv/bin/python -m tank_vision mc.jpg
    .venv/bin/python -m tank_vision mc.jpg --point 0.335,0.32
    .venv/bin/python -m tank_vision mc.jpg --focus 0.11,0.60,0.31,0.81
    .venv/bin/python -m tank_vision frame.jpg --detect-only

Writes <stem>_result.json, <stem>_overlay.png and one <stem>_mask_N.png per
object into --out (default vision_out/). Coordinates are normalized 0..1,
origin top-left — the same numbers the phone will send.

Empty results are success: JSON says "objects": [] and the overlay is just
the input. That is the honest answer for e.g. a circuit board under a
COCO-trained detector, and the GUI must show it as 'nothing recognised'.
"""

import argparse
import json
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tank_vision.pipeline import Box, VisionPipeline  # noqa: E402

COLORS = [(255, 80, 80), (80, 255, 120), (80, 160, 255), (255, 200, 80),
          (220, 80, 255), (80, 255, 230)]


def _parse_box(text):
    parts = [float(v) for v in text.split(",")]
    if len(parts) == 2:
        return ("point", parts)
    if len(parts) == 4:
        return ("box", Box(*parts))
    raise argparse.ArgumentTypeError("expected x,y or x0,y0,x1,y1")


def render_overlay(img, segmented_list):
    """Boxes + translucent masks + centroid dots, Pillow only."""
    base = img.convert("RGB")
    tint = Image.new("RGB", base.size, (0, 0, 0))
    draw_src = ImageDraw.Draw(base)
    for i, seg in enumerate(segmented_list):
        color = COLORS[i % len(COLORS)]
        s = seg.summary()
        if s.get("empty"):
            continue
        tint.paste(Image.new("RGB", base.size, color), (0, 0), seg.mask)
        mb = s["mask_box"]
        w, h = base.size
        draw_src.rectangle([mb["x0"] * w, mb["y0"] * h, mb["x1"] * w, mb["y1"] * h],
                           outline=color, width=max(2, w // 400))
        cx, cy = s["centroid"]["x"] * w, s["centroid"]["y"] * h
        r = max(4, w // 200)
        draw_src.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
        label = seg.label or seg.source
        draw_src.text((mb["x0"] * w + 4, max(0, mb["y0"] * h - 14)),
                      f"{label} {seg.confidence:.2f}" if seg.confidence else label,
                      fill=color)
    return Image.blend(base, Image.blend(base, tint, 0.45), 0.85)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image")
    ap.add_argument("--point", type=_parse_box, default=None,
                    help="tap focus / raw point prompt: x,y (normalized)")
    ap.add_argument("--box", type=_parse_box, default=None,
                    help="raw SAM box prompt: x0,y0,x1,y1 (normalized)")
    ap.add_argument("--focus", type=_parse_box, default=None,
                    help="'go check that out': x0,y0,x1,y1 or x,y (normalized)")
    ap.add_argument("--detect-only", action="store_true",
                    help="YOLO only, skip SAM")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--out", default="vision_out")
    args = ap.parse_args(argv)

    pipe = VisionPipeline(confidence=args.conf)
    img = Image.open(args.image).convert("RGB")
    stem = os.path.splitext(os.path.basename(args.image))[0]
    os.makedirs(args.out, exist_ok=True)

    segmented, payload = [], {"image": args.image, "size": list(img.size),
                              "objects": [], "detections": []}
    if args.detect_only:
        payload["detections"] = [d.as_dict() for d in pipe.detect(img)]
    elif args.focus is not None:
        kind, val = args.focus
        seg = (pipe.focus_point(img, val[0], val[1]) if kind == "point"
               else pipe.focus(img, val))
        segmented = [seg]
    elif args.point is not None:
        _, (x, y) = args.point
        segmented = [pipe.mask_from_point(img, x, y)]
    elif args.box is not None:
        segmented = [pipe.mask_from_box(img, args.box[1])]
    else:
        segmented = pipe.detect_and_segment(img)

    if not args.detect_only and segmented and segmented[0].source == "yolo":
        payload["detections"] = [
            {"label": s.label, "confidence": round(s.confidence, 3),
             "box": s.prompt_box.as_dict()} for s in segmented]
    for i, seg in enumerate(segmented):
        entry = seg.summary()
        entry["aim"] = VisionPipeline.aim(seg)
        payload["objects"].append(entry)
        seg.mask.save(os.path.join(args.out, f"{stem}_mask_{i}.png"))

    render_overlay(img, segmented).save(os.path.join(args.out, f"{stem}_overlay.png"))
    with open(os.path.join(args.out, f"{stem}_result.json"), "w") as f:
        json.dump(payload, f, indent=1)
    print(json.dumps(payload, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
