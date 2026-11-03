"""YOLO -> SAM pipeline with phone-shaped prompts.

Backends are pluggable so the plumbing is testable without torch: the real
backend wraps Ultralytics (YOLO11 for boxes, MobileSAM for masks — one
dependency, weights fetched on first use). Tests inject fakes.

Mask representation: PIL Image mode "L" (255 = inside). Summaries carry
normalized geometry (mask bbox, centroid, area fraction) because that is
what the phone GUI and later the drive-to-target loop consume.
"""

import os
from dataclasses import dataclass, field

from PIL import Image

# Weights live in the project so a downloaded pair survives across the
# desktop/Pi and is never hunted for in a user cache. Set TANK_VISION_HOME
# to override (e.g. a shared weights dir on the Pi).
WEIGHTS_DIR = os.environ.get(
    "TANK_VISION_HOME", os.path.join(os.path.dirname(os.path.abspath(__file__)), "weights"))


@dataclass(frozen=True)
class Box:
    """Normalized box, origin top-left. x1 > x0, y1 > y0, all in 0..1."""

    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self):
        for v in (self.x0, self.y0, self.x1, self.y1):
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"box coordinate {v} outside 0..1")
        if not (self.x1 > self.x0 and self.y1 > self.y0):
            raise ValueError("box must satisfy x1 > x0 and y1 > y0")

    def to_pixels(self, width, height):
        return (round(self.x0 * width), round(self.y0 * height),
                round(self.x1 * width), round(self.y1 * height))

    @classmethod
    def from_pixels(cls, box, width, height):
        x0, y0, x1, y1 = box
        return cls(x0 / width, y0 / height, x1 / width, y1 / height)

    def as_dict(self):
        return {"x0": round(self.x0, 4), "y0": round(self.y0, 4),
                "x1": round(self.x1, 4), "y1": round(self.y1, 4)}


@dataclass
class Detection:
    label: str
    confidence: float
    box: Box  # normalized

    def as_dict(self):
        return {"label": self.label, "confidence": round(self.confidence, 3),
                "box": self.box.as_dict()}


@dataclass
class Segmented:
    source: str  # "yolo" | "point" | "box"
    mask: Image.Image = field(repr=False)  # mode "L", full image size
    label: str = ""
    confidence: float = 0.0
    prompt_box: Box = None  # box handed to SAM (normalized), if any
    prompt_point: tuple = None  # (x, y) normalized, if any

    def summary(self):
        """JSON-ready geometry. Centroid/area are the aim signal for the GUI."""
        w, h = self.mask.size
        bbox = self.mask.getbbox()  # pixel bbox of nonzero, or None
        total = w * h
        inside = sum(1 for v in self.mask.getdata() if v)
        if bbox is None or inside == 0:
            return {"source": self.source, "label": self.label,
                    "confidence": round(self.confidence, 3), "empty": True}
        # Centroid from row/column sums — fine at phone-frame sizes.
        px = self.mask.load()
        sx = sy = 0
        for yy in range(h):
            for xx in range(w):
                if px[xx, yy]:
                    sx += xx
                    sy += yy
        return {
            "source": self.source, "label": self.label,
            "confidence": round(self.confidence, 3), "empty": False,
            "mask_box": Box.from_pixels(bbox, w, h).as_dict(),
            "centroid": {"x": round((sx / inside) / w, 4),
                         "y": round((sy / inside) / h, 4)},
            "area_frac": round(inside / total, 4),
        }


def _check_point(x, y):
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ValueError(f"point ({x}, {y}) outside 0..1")


class VisionPipeline:
    """detect (YOLO) + segment (SAM), with tap/drag prompt entry points."""

    def __init__(self, detector=None, segmenter=None,
                 yolo_weights="yolo11n.pt", sam_weights="mobile_sam.pt",
                 confidence=0.25):
        # Injected backends (tests) skip ultralytics entirely.
        self._detector = detector
        self._segmenter = segmenter
        self._yolo_weights = yolo_weights
        self._sam_weights = sam_weights
        self.confidence = confidence

    # -- backend loading (lazy, real models only on first real call) ----
    def _load(self):
        if self._detector is not None and self._segmenter is not None:
            return
        try:
            from ultralytics import SAM, YOLO
        except ImportError as e:
            raise RuntimeError(
                "ultralytics is not installed in this environment. "
                "Desktop: .venv/bin/pip install ultralytics  (see src/tank_vision/README.md)"
            ) from e
        os.makedirs(WEIGHTS_DIR, exist_ok=True)
        if self._detector is None:
            self._detector = _UltralyticsDetector(
                YOLO(os.path.join(WEIGHTS_DIR, self._yolo_weights)))
        if self._segmenter is None:
            self._segmenter = _UltralyticsSegmenter(
                SAM(os.path.join(WEIGHTS_DIR, self._sam_weights)))

    # -- public API ------------------------------------------------------
    def detect(self, image):
        """YOLO only. Returns list[Detection]; [] means 'nothing known here'."""
        self._load()
        img = _as_image(image)
        return self._detector.detect(img, self.confidence)

    def mask_from_point(self, image, x, y):
        """Phone tap: segment whatever object sits at normalized (x, y)."""
        _check_point(x, y)
        self._load()
        img = _as_image(image)
        w, h = img.size
        mask = self._segmenter.segment(img, point=(x * w, y * h))
        return Segmented(source="point", mask=mask, prompt_point=(x, y))

    def mask_from_box(self, image, box):
        """Phone drag: segment the main object inside normalized `box`."""
        if not isinstance(box, Box):
            box = Box(*box)
        self._load()
        img = _as_image(image)
        w, h = img.size
        mask = self._segmenter.segment(img, box=box.to_pixels(w, h))
        return Segmented(source="box", mask=mask, prompt_box=box)

    def focus(self, image, box):
        """User-drawn focus box: 'investigate this / go check that out'.

        Picks the best YOLO detection whose centre falls inside the box and
        segments that object. If YOLO knows nothing there, falls back to a
        direct SAM box prompt — the user's region always yields a target (or
        an empty mask, reported honestly). The result's centroid vs. frame
        centre is the aim error for pan/tilt/drive in later stages.
        """
        if not isinstance(box, Box):
            box = Box(*box)
        self._load()
        img = _as_image(image)
        w, h = img.size
        inside = []
        for det in self._detector.detect(img, self.confidence):
            cx = (det.box.x0 + det.box.x1) / 2
            cy = (det.box.y0 + det.box.y1) / 2
            if box.x0 <= cx <= box.x1 and box.y0 <= cy <= box.y1:
                inside.append(det)
        if inside:
            best = max(inside, key=lambda d: d.confidence)
            mask = self._segmenter.segment(img, box=best.box.to_pixels(w, h))
            return Segmented(source="focus-detect", mask=mask, label=best.label,
                             confidence=best.confidence, prompt_box=box)
        mask = self._segmenter.segment(img, box=box.to_pixels(w, h))
        return Segmented(source="focus-box", mask=mask, prompt_box=box)

    def focus_point(self, image, x, y, radius=0.06):
        """Tap variant of focus(): a small box around the tapped point."""
        _check_point(x, y)
        box = Box(max(0.0, x - radius), max(0.0, y - radius),
                  min(1.0, x + radius), min(1.0, y + radius))
        seg = self.focus(image, box)
        seg.prompt_point = (x, y)
        return seg

    @staticmethod
    def aim(segmented):
        """Centroid offset from frame centre: +right / +up, each in -0.5..0.5.

        None when the mask is empty — callers must treat that as 'no target',
        never as 'drive straight'. Sign convention matches tank_phone's
        tap_preview (dx = x - 0.5, dy = 0.5 - y).
        """
        s = segmented.summary()
        if s.get("empty"):
            return None
        c = s["centroid"]
        return {"dx_right": round(c["x"] - 0.5, 4),
                "dy_up": round(0.5 - c["y"], 4),
                "area_frac": s["area_frac"]}

    def detect_and_segment(self, image):
        """Auto path: every YOLO box becomes a SAM prompt. [] stays []."""
        self._load()
        img = _as_image(image)
        w, h = img.size
        out = []
        for det in self._detector.detect(img, self.confidence):
            mask = self._segmenter.segment(img, box=det.box.to_pixels(w, h))
            out.append(Segmented(source="yolo", mask=mask, label=det.label,
                                 confidence=det.confidence, prompt_box=det.box))
        return out


def _as_image(image):
    if isinstance(image, Image.Image):
        return image.convert("RGB")
    return Image.open(image).convert("RGB")


# -- Ultralytics adapters (only imported/used with real weights) ----------

class _UltralyticsDetector:
    def __init__(self, model):
        self._model = model

    def detect(self, img, confidence):
        w, h = img.size
        result = self._model.predict(img, conf=confidence, verbose=False)[0]
        out = []
        for box in result.boxes:
            x0, y0, x1, y1 = (float(v) for v in box.xyxy[0].tolist())
            out.append(Detection(
                label=result.names[int(box.cls[0])],
                confidence=float(box.conf[0]),
                box=Box.from_pixels((x0, y0, x1, y1), w, h)))
        return out


class _UltralyticsSegmenter:
    def __init__(self, model):
        self._model = model

    def segment(self, img, point=None, box=None):
        kwargs = {"verbose": False}
        if point is not None:
            kwargs["points"] = [[point[0], point[1]]]
            kwargs["labels"] = [1]
        if box is not None:
            kwargs["bboxes"] = [[box[0], box[1], box[2], box[3]]]
        result = self._model.predict(img, **kwargs)[0]
        if result.masks is None or len(result.masks.data) == 0:
            return Image.new("L", img.size, 0)
        # First mask wins: SAM's top-scored candidate for the prompt.
        import numpy as np
        data = result.masks.data[0].cpu().numpy()
        mask = Image.fromarray((data * 255).astype("uint8"), mode="L")
        if mask.size != img.size:
            mask = mask.resize(img.size)
        return mask
