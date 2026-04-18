"""
Multi-region calibration: up to 4 independent detection zones,
each mapped to a single note.

Each zone is a camera-space quadrilateral; detection checks whether a
blob centroid falls inside it using a point-in-polygon test.
"""

from typing import Any, Dict, List, Optional
import cv2
import numpy as np


MAX_REGIONS = 4

# Per-region colours (BGR) for CV annotations
REGION_COLOURS_BGR = [
    (247, 142,  79),   # blue   (#4f8ef7)
    (122, 194,  52),   # green  (#34c27a)
    ( 50, 168, 240),   # orange (#f0a832)
    ( 82,  82, 224),   # red    (#e05252)
]


class DetectionRegion:
    """A single quadrilateral zone with an associated note."""

    def __init__(self, points: List[List[int]], note: str):
        self.points: List[List[int]] = points   # 4 [x, y] camera-space pairs
        self.note: str = note                   # e.g. "C4"

    def point_in_region(self, x: int, y: int) -> bool:
        if len(self.points) != 4:
            return False
        poly = np.array(self.points, dtype=np.int32)
        return cv2.pointPolygonTest(poly, (float(x), float(y)), False) >= 0

    def to_dict(self) -> Dict:
        return {"points": self.points, "note": self.note}

    @classmethod
    def from_dict(cls, data: Dict) -> "DetectionRegion":
        return cls(data["points"], data.get("note", "C4"))


class CalibrationManager:
    """Manages up to MAX_REGIONS detection zones, each with a note."""

    def __init__(self):
        self.regions: List[DetectionRegion] = []

    @property
    def is_calibrated(self) -> bool:
        return len(self.regions) > 0

    def set_regions(self, region_list: List[Dict]) -> bool:
        """
        Accept a list of dicts: [{"points": [[x,y]×4], "note": "C4"}, ...]
        Validates and stores up to MAX_REGIONS entries. Returns True on success.
        """
        if not region_list or len(region_list) > MAX_REGIONS:
            return False
        new_regions = []
        for r in region_list:
            pts = r.get("points", [])
            if len(pts) != 4:
                return False
            new_regions.append(DetectionRegion(pts, r.get("note", "C4")))
        self.regions = new_regions
        return True

    def point_in_any_region(self, x: int, y: int) -> int:
        """Return the index of the first region containing (x, y), or -1."""
        for i, region in enumerate(self.regions):
            if region.point_in_region(x, y):
                return i
        return -1

    def get_regions_camera_space(self) -> List[Dict]:
        """Return per-region dicts with points, note and colour for CV drawing."""
        return [
            {
                "region_index": i,
                "points": r.points,
                "note": r.note,
                "color": REGION_COLOURS_BGR[i % len(REGION_COLOURS_BGR)],
            }
            for i, r in enumerate(self.regions)
        ]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regions": [r.to_dict() for r in self.regions],
            "is_calibrated": self.is_calibrated,
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        regions_data = data.get("regions", [])
        self.regions = [DetectionRegion.from_dict(r) for r in regions_data if r.get("points")]
