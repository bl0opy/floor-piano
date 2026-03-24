"""
Calibration: maps a camera-space quadrilateral to a normalised top-down
floor space, then divides that space into equal-width piano key columns.

Coordinate convention
---------------------
Camera space  : pixel (x, y) as seen in the video frame
Floor space   : normalised (tx, ty) where x ∈ [0,1] spans the keyboard
                left→right, y ∈ [0,1] spans front→back
Key index     : floor(tx * num_keys), clamped to [0, num_keys-1]
"""

from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


class CalibrationManager:
    def __init__(self):
        self.region_points: List[List[int]] = []   # 4 corners in camera space
        self.num_keys: int = 8
        self.homography: Optional[np.ndarray] = None      # camera → floor
        self.inv_homography: Optional[np.ndarray] = None  # floor → camera
        self.is_calibrated: bool = False

    # ------------------------------------------------------------------
    # Setting up calibration
    # ------------------------------------------------------------------

    def set_region(self, points: List[List[int]], num_keys: int) -> bool:
        """
        Compute homography from the four user-supplied corner points.
        Returns True on success.
        """
        if len(points) != 4:
            return False
        self.region_points = points
        self.num_keys = max(1, num_keys)
        self._compute_homography()
        self.is_calibrated = self.homography is not None
        return self.is_calibrated

    def _order_points(self, pts: np.ndarray) -> np.ndarray:
        """Sort four points into (top-left, top-right, bottom-right, bottom-left)."""
        rect = np.zeros((4, 2), dtype=np.float32)
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]   # top-left: smallest x+y
        rect[2] = pts[np.argmax(s)]   # bottom-right: largest x+y
        d = pts[:, 1] - pts[:, 0]     # y - x
        rect[1] = pts[np.argmin(d)]   # top-right: smallest y-x (large x, small y)
        rect[3] = pts[np.argmax(d)]   # bottom-left: largest y-x
        return rect

    def _compute_homography(self) -> None:
        src = self._order_points(np.array(self.region_points, dtype=np.float32))
        dst = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
        self.homography, _ = cv2.findHomography(src, dst)
        self.inv_homography, _ = cv2.findHomography(dst, src)

    # ------------------------------------------------------------------
    # Runtime queries
    # ------------------------------------------------------------------

    def transform_point(self, x: int, y: int) -> Optional[Tuple[float, float]]:
        """Project a camera-space point into normalised floor space."""
        if self.homography is None:
            return None
        pt = np.array([[[float(x), float(y)]]], dtype=np.float32)
        tx, ty = cv2.perspectiveTransform(pt, self.homography)[0][0]
        return float(tx), float(ty)

    def point_in_region(self, x: int, y: int) -> bool:
        """Return True if the camera-space point is inside the calibration polygon."""
        if not self.region_points:
            return False
        poly = np.array(self.region_points, dtype=np.int32)
        return cv2.pointPolygonTest(poly, (float(x), float(y)), False) >= 0

    def get_key_index(self, floor_x: float) -> int:
        idx = int(floor_x * self.num_keys)
        return max(0, min(self.num_keys - 1, idx))

    def get_key_regions_camera_space(self) -> List[Dict]:
        """
        Return per-key quadrilateral corners in camera space.
        Used by the CV pipeline to draw key boundaries on frames.
        """
        if not self.is_calibrated or self.inv_homography is None:
            return []
        regions = []
        for i in range(self.num_keys):
            xl = i / self.num_keys
            xr = (i + 1) / self.num_keys
            corners = np.array(
                [[[xl, 0]], [[xr, 0]], [[xr, 1]], [[xl, 1]]], dtype=np.float32
            )
            cam = cv2.perspectiveTransform(corners, self.inv_homography)
            regions.append({
                "key_index": i,
                "points": cam.reshape(-1, 2).astype(int).tolist(),
            })
        return regions

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region_points": self.region_points,
            "num_keys": self.num_keys,
            "is_calibrated": self.is_calibrated,
            "homography": self.homography.tolist() if self.homography is not None else None,
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        self.region_points = data.get("region_points", [])
        self.num_keys = data.get("num_keys", 8)
        h = data.get("homography")
        if h and self.region_points:
            self.homography = np.array(h, dtype=np.float64)
            # Re-derive the inverse from the saved region points
            src = self._order_points(np.array(self.region_points, dtype=np.float32))
            dst = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
            self.inv_homography, _ = cv2.findHomography(dst, src)
            self.is_calibrated = True
        else:
            self.is_calibrated = False
