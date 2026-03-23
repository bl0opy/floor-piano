"""
CV detection pipeline.

Runs a dedicated background thread that:
  1. Reads frames from the camera (or any OpenCV-compatible source)
  2. Applies MOG2 background subtraction inside the calibrated region
  3. Finds foreground blobs (feet) via contour analysis
  4. Maps blob centroids through the homography to the piano key index
  5. Applies per-key debounce/cooldown
  6. Fires on_key_triggered(key_index) callback
  7. Produces JPEG-encoded annotated frames for the MJPEG stream

All public attributes and methods are safe to call from the main thread.
"""

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .calibration import CalibrationManager

# Colour palette (BGR)
COL_KEY_FILL   = (40,  40,  80)
COL_KEY_BORDER = (180, 180, 180)
COL_KEY_ACTIVE = (50,  255, 120)
COL_BLOB       = (0,   255, 255)
COL_TEXT       = (255, 255, 255)
COL_STATUS_OK  = (50,  220, 50)
COL_STATUS_OFF = (30,  140, 255)

# How long after a key fires to keep the on-screen glow (seconds)
KEY_HIGHLIGHT_TTL = 0.55


class DetectionPipeline:
    """Thread-safe camera capture + step detection pipeline."""

    def __init__(self, calibration: CalibrationManager):
        self.calibration = calibration

        # ---- Camera / thread state ----
        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

        # ---- Frame buffers ----
        self._latest_jpeg: Optional[bytes] = None
        self.frame_width = 640
        self.frame_height = 480

        # ---- Detection state ----
        self._detection_enabled = False
        self._bg_sub = self._make_bg_sub()

        # Per-key cooldown: key_index → absolute timestamp when next trigger allowed
        self._cooldown_until: Dict[int, float] = {}

        # Currently highlighted key for the on-screen glow
        self._active_key: Optional[int] = None
        self._active_key_ts: float = 0.0

        # ---- Settings (updated live from server) ----
        self.settings: Dict[str, Any] = {
            "sensitivity": 60,
            "min_blob_area": 800,
            "cooldown_ms": 400,
            "jpeg_quality": 75,
            "debug_mode": False,
        }

        # ---- Callback (set by server) ----
        self.on_key_triggered: Optional[Callable[[int], None]] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, camera_source: Any = 0) -> bool:
        if self._running:
            return True
        self._cap = cv2.VideoCapture(camera_source)
        if not self._cap.isOpened():
            print(f"[CV] Cannot open camera: {camera_source!r}")
            return False
        self.frame_width  = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.frame_height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[CV] Camera {camera_source!r} opened ({self.frame_width}×{self.frame_height})")
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="cv-pipeline")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        if self._cap:
            self._cap.release()
            self._cap = None
        print("[CV] Pipeline stopped")

    def restart_camera(self, camera_source: Any = 0) -> bool:
        self.stop()
        return self.start(camera_source)

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def enable_detection(self, enabled: bool) -> None:
        self._detection_enabled = enabled
        if enabled:
            # Fresh background model so the current scene becomes the background
            self._bg_sub = self._make_bg_sub()
            print("[CV] Detection enabled — learning background…")
        else:
            print("[CV] Detection disabled")

    def configure(self, settings: Dict[str, Any]) -> None:
        self.settings.update(settings)

    # ------------------------------------------------------------------
    # Frame access (main thread / MJPEG generator)
    # ------------------------------------------------------------------

    def get_latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    def get_state(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "detection_enabled": self._detection_enabled,
            "active_key": self._active_key,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
        }

    # ------------------------------------------------------------------
    # Main capture loop (background thread)
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        target_interval = 1.0 / 30.0   # 30 fps cap
        while self._running:
            t0 = time.monotonic()
            ret, frame = self._cap.read()
            if not ret:
                # Camera stalled — give it a moment
                time.sleep(0.05)
                continue

            annotated = self._process(frame)

            quality = self.settings.get("jpeg_quality", 75)
            ok, jpeg_buf = cv2.imencode(
                ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, quality]
            )
            if ok:
                with self._lock:
                    self._latest_jpeg = jpeg_buf.tobytes()

            elapsed = time.monotonic() - t0
            sleep = target_interval - elapsed
            if sleep > 0:
                time.sleep(sleep)

    # ------------------------------------------------------------------
    # Per-frame processing
    # ------------------------------------------------------------------

    def _process(self, frame: np.ndarray) -> np.ndarray:
        out = frame.copy()

        if self.calibration.is_calibrated:
            self._draw_key_grid(out)

        if self._detection_enabled and self.calibration.is_calibrated:
            blobs = self._detect(frame)
            self._draw_blobs(out, blobs)
            self._handle_detections(blobs)

        # Fade-out key glow
        if self._active_key is not None:
            age = time.monotonic() - self._active_key_ts
            if age < KEY_HIGHLIGHT_TTL:
                self._draw_active_key(out, self._active_key, age)
            else:
                self._active_key = None

        self._draw_hud(out)
        return out

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------

    def _detect(self, frame: np.ndarray) -> List[Tuple[int, int]]:
        """Return list of blob centroid (x,y) in camera space."""
        sensitivity  = int(self.settings.get("sensitivity", 60))
        min_area     = int(self.settings.get("min_blob_area", 800))

        # Sensitivity 0-100 → varThreshold 90-10 (higher threshold = less sensitive)
        self._bg_sub.setVarThreshold(max(10, 100 - sensitivity))

        mask = self._bg_sub.apply(frame)

        # Restrict to calibrated region
        roi_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        if self.calibration.region_points:
            poly = np.array(self.calibration.region_points, dtype=np.int32)
            cv2.fillPoly(roi_mask, [poly], 255)
        mask = cv2.bitwise_and(mask, roi_mask)

        # Morphological clean-up: remove speckle, fill gaps
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
        mask = cv2.dilate(mask, k, iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        centroids = []
        for c in contours:
            if cv2.contourArea(c) < min_area:
                continue
            M = cv2.moments(c)
            if M["m00"] == 0:
                continue
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            if self.calibration.point_in_region(cx, cy):
                centroids.append((cx, cy))

        return centroids

    def _handle_detections(self, blobs: List[Tuple[int, int]]) -> None:
        cooldown = self.settings.get("cooldown_ms", 400) / 1000.0
        now = time.monotonic()

        for bx, by in blobs:
            coord = self.calibration.transform_point(bx, by)
            if coord is None:
                continue
            fx, fy = coord
            if not (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0):
                continue

            key = self.calibration.get_key_index(fx)
            if now < self._cooldown_until.get(key, 0.0):
                continue

            # Fire!
            self._cooldown_until[key] = now + cooldown
            self._active_key = key
            self._active_key_ts = now

            if self.on_key_triggered:
                try:
                    self.on_key_triggered(key)
                except Exception as e:
                    print(f"[CV] on_key_triggered error: {e}")

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _draw_key_grid(self, frame: np.ndarray) -> None:
        regions = self.calibration.get_key_regions_camera_space()
        overlay = frame.copy()
        for r in regions:
            pts = np.array(r["points"], dtype=np.int32)
            cv2.fillPoly(overlay, [pts], COL_KEY_FILL)
        cv2.addWeighted(overlay, 0.25, frame, 0.75, 0, frame)

        for r in regions:
            pts = np.array(r["points"], dtype=np.int32)
            cv2.polylines(frame, [pts], isClosed=True, color=COL_KEY_BORDER, thickness=1)
            cx = int(np.mean([p[0] for p in r["points"]]))
            cy = int(np.mean([p[1] for p in r["points"]]))
            cv2.putText(frame, str(r["key_index"] + 1),
                        (cx - 6, cy + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, COL_TEXT, 1,
                        cv2.LINE_AA)

    def _draw_blobs(self, frame: np.ndarray, blobs: List[Tuple[int, int]]) -> None:
        for bx, by in blobs:
            cv2.circle(frame, (bx, by), 18, COL_BLOB, 2)
            cv2.circle(frame, (bx, by),  4, COL_BLOB, -1)

    def _draw_active_key(self, frame: np.ndarray, key_index: int, age: float) -> None:
        regions = self.calibration.get_key_regions_camera_space()
        for r in regions:
            if r["key_index"] != key_index:
                continue
            pts = np.array(r["points"], dtype=np.int32)
            alpha = max(0.0, 1.0 - age / KEY_HIGHLIGHT_TTL) * 0.55
            overlay = frame.copy()
            cv2.fillPoly(overlay, [pts], COL_KEY_ACTIVE)
            cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)
            cv2.polylines(frame, [pts], True, COL_KEY_ACTIVE, 2)
            break

    def _draw_hud(self, frame: np.ndarray) -> None:
        if self._detection_enabled:
            label, col = "DETECTING", COL_STATUS_OK
        else:
            label, col = "PAUSED", COL_STATUS_OFF
        cv2.putText(frame, label, (10, 26), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, col, 2, cv2.LINE_AA)
        if not self.calibration.is_calibrated:
            cv2.putText(frame, "NOT CALIBRATED — draw region in UI",
                        (10, 52), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, COL_STATUS_OFF, 1, cv2.LINE_AA)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_bg_sub() -> cv2.BackgroundSubtractorMOG2:
        return cv2.createBackgroundSubtractorMOG2(
            history=300, varThreshold=50, detectShadows=False
        )
