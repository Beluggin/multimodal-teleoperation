"""tank_vision — YOLO detection + SAM segmentation for the tank demo.

Public surface (the same three calls the phone GUI will make):

    pipe = VisionPipeline()                  # lazy: loads models on first use
    objs = pipe.detect_and_segment(image)    # auto: YOLO boxes -> SAM masks
    obj  = pipe.focus(image, box)            # drag: 'go check that out'
    obj  = pipe.focus_point(image, x, y)     # tap:  same, around a point
    obj  = pipe.mask_from_point(image, x, y) # raw SAM point prompt (x, y in 0..1)
    obj  = pipe.mask_from_box(image, box)    # raw SAM box prompt  (Box in 0..1)
    aim  = pipe.aim(obj)                     # centroid offset, or None = no target

Coordinates at this boundary are normalized 0..1 (origin top-left), matching
tank_phone's tap contract. Pixel conversion happens inside the pipeline.

Safety posture (same as the rest of the repo): no detections is a normal,
empty result — never an error, never a guess. Bad coordinates raise
ValueError. Nothing in this package touches motors, servos, or the bus.
"""

from tank_vision.pipeline import Box, Detection, Segmented, VisionPipeline

__all__ = ["Box", "Detection", "Segmented", "VisionPipeline"]
