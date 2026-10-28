#!/usr/bin/env python3
"""meta_sam.py — SAM 3.1 via the Meta Model API (the hackathon flagship path).

    MODEL_API_KEY=... python3 -m tank_vision.meta_sam mc.jpg "silver capacitor"
    MODEL_API_KEY=... python3 -m tank_vision.meta_sam --probe mc.jpg "red cup"

No HF gate, no GPU: SAM 3.1 is hosted at api.meta.ai, model id `sam-3.1`,
text prompt + image in, boxes + masks out, billed per image against the
hackathon Model API credits. The key comes from the environment ONLY —
never from the repo, never printed. (AGENTS.md: API requests stay limited
to deliberate demo input; this sends exactly the image + prompt given.)

The parser is deliberately tolerant and the --probe mode dumps the raw
response, because the exact mask encoding gets confirmed against one real
response before anyone trusts the geometry downstream.
"""

import argparse
import base64
import io
import json
import os
import re
import sys
import urllib.request

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tank_vision.pipeline import Box, Segmented  # noqa: E402

API_URL = os.environ.get("META_API_BASE", "https://api.meta.ai/v1") + "/responses"
MODEL = "sam-3.1"
MAX_SIDE = 1280


def _image_part(image):
    img = image if isinstance(image, Image.Image) else Image.open(image)
    img = img.convert("RGB")
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"}, img.size


def build_request(image, prompt):
    part, size = _image_part(image)
    return ({"model": MODEL,
             "input": [{"role": "user",
                        "content": [part, {"type": "input_text", "text": prompt}]}]},
            size)


def call_api(payload, api_key, timeout=120):
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"}, method="POST")
    # Default opener honours env proxies (the Muse sandbox broker needs
    # them for api.meta.ai; the Pi/desktop simply have none set).
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def decode_rle(rle, size):
    """COCO uncompressed RLE {size:[h,w], counts:[...]} -> PIL 'L' mask."""
    h, w = rle["size"]
    counts = rle["counts"]
    if isinstance(counts, str):
        raise ValueError("compressed RLE string: parser needs the real "
                         "response shape first (run --probe)")
    flat = bytearray(w * h)
    idx, val = 0, 0
    for run in counts:
        flat[idx:idx + run] = bytes([255 if val else 0]) * run
        idx += run
        val = 1 - val
    # COCO RLE is column-major (Fortran order).
    return _fortran_to_image(flat, w, h)


def _fortran_to_image(flat, w, h):
    img = Image.new("L", (w, h))
    px = img.load()
    i = 0
    for x in range(w):
        for y in range(h):
            px[x, y] = flat[i]
            i += 1
    return img


_TAG_RE = re.compile(r"<\|(box|mask);([^|]*)\|>")


def parse_sam_text(text, prompt):
    """SAM 3.1 wire text -> [{box: Box (normalized), mask_tag: str|None}].

    Pairs of <|box;...|><|mask;...|> per object instance, in order.
    Verified against a real response (mc.jpg, 'silver capacitor': 4 boxes).
    """
    records, current = [], None
    for kind, attrs in _TAG_RE.findall(text):
        fields = {}
        for part in attrs.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                fields[k.strip()] = v
        if kind == "box":
            w, h = float(fields["w"]), float(fields["h"])
            current = {"box": Box(float(fields["x1"]) / w, float(fields["y1"]) / h,
                                  float(fields["x2"]) / w, float(fields["y2"]) / h),
                       "mask_tag": None, "label": prompt}
            records.append(current)
        elif current is not None:
            current["mask_tag"] = attrs
    return records


def _official_objects(text, image_size, prompt):
    """Real masks via Meta's meta_sam_parser. None if not installed.

    The wire encoding (base85, box-local rasters) is Meta's own; we feed
    the raw output text to their incremental parser and compose each
    box-local raster into a full-frame PIL mask at its bounds.
    """
    try:
        from meta_sam_parser import (CompletedOutcome, decode_mask_to_raster,
                                      image_segmentation_format)
    except ImportError:
        return None
    parser = image_segmentation_format().create_parser()
    parser.push(text)
    result = parser.finish(CompletedOutcome()).result
    w, h = image_size
    boxes = {r.object_id: r for r in result.records if r.kind == "box"}
    objects = []
    for rec in result.records:
        if rec.kind != "mask":
            continue
        raster = decode_mask_to_raster(rec.mask)  # bytes 0/1, row-major
        tile = Image.frombytes("L", (rec.mask.width, rec.mask.height),
                               bytes(255 * b for b in raster))
        full = Image.new("L", (w, h), 0)
        full.paste(tile, (round(rec.bounds.left), round(rec.bounds.top)))
        box_rec = boxes.get(rec.object_id)
        pbox = None
        if box_rec is not None:
            pbox = Box(box_rec.left / w, box_rec.top / h,
                       box_rec.right / w, box_rec.bottom / h)
        objects.append(Segmented(source="sam3-mask", mask=full, label=prompt,
                                 confidence=rec.confidence or 0.0,
                                 prompt_box=pbox))
    return objects


def parse_response(data, image_size, prompt):
    text = ""
    for item in data.get("output", []):
        for part in item.get("content", []):
            if part.get("type") == "output_text":
                text = part.get("text", "")
    official = _official_objects(text, image_size, prompt)
    if official is not None:
        return official
    # Fallback without meta-sam-parser: box-fill masks. Geometry
    # (centroid/aim) comes from SAM's own boxes; labelled sam3-box,
    # never presented as pixel masks.
    from PIL import ImageDraw
    objects = []
    for rec in parse_sam_text(text, prompt):
        mask = Image.new("L", image_size, 0)
        ImageDraw.Draw(mask).rectangle(
            list(rec["box"].to_pixels(*image_size)), fill=255)
        objects.append(Segmented(source="sam3-box", mask=mask,
                                 label=rec["label"], prompt_box=rec["box"]))
    return objects


def segment_text(image, prompt, api_key=None, timeout=120):
    api_key = api_key or os.environ.get("MODEL_API_KEY", "")
    if not api_key:
        raise RuntimeError("MODEL_API_KEY not set (environment only, never commit it)")
    payload, size = build_request(image, prompt)
    data = call_api(payload, api_key, timeout=timeout)
    return parse_response(data, size, prompt), data


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image")
    ap.add_argument("prompt")
    ap.add_argument("--probe", action="store_true",
                    help="dump raw response JSON to vision_out/meta_probe.json")
    ap.add_argument("--out", default="vision_out/meta")
    args = ap.parse_args(argv)

    objects, data = segment_text(args.image, args.prompt)
    os.makedirs(args.out, exist_ok=True)
    if args.probe:
        path = os.path.join(args.out, "meta_probe.json")
        with open(path, "w") as f:
            json.dump(data, f, indent=1)
        print(f"raw response saved to {path} "
              f"({len(json.dumps(data))} bytes) — paste its structure back")
    summaries = []
    for i, obj in enumerate(objects):
        summaries.append(obj.summary())
        obj.mask.save(os.path.join(args.out, f"mask_{i}.png"))
    print(json.dumps({"model": MODEL, "objects": summaries}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
