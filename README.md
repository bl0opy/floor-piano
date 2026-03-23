# 🎹 Floor Piano

An interactive floor piano that uses a camera to track where a person steps and plays the corresponding piano note in real time.

A piano keyboard region is drawn on the floor (projected or taped). The system watches via webcam, detects foot contacts using background subtraction, maps the detected position to a key, and plays the audio.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│  Browser (localhost:8000)                           │
│  ┌───────────────┐  ┌──────────────────────────┐   │
│  │  MJPEG <img>  │  │  WebSocket (key events)  │   │
│  │  /video_feed  │  │  /ws                     │   │
│  └───────┬───────┘  └─────────────┬────────────┘   │
└──────────┼─────────────────────────┼───────────────┘
           │                         │
┌──────────▼─────────────────────────▼───────────────┐
│  FastAPI server  (backend/server.py)                │
│   REST API  ·  MJPEG stream  ·  WS broadcaster     │
└──────────────────────┬──────────────────────────────┘
                       │
        ┌──────────────┼─────────────┐
        ▼              ▼             ▼
  DetectionPipeline  Audio       CalibrationManager
  (cv_pipeline.py)   Engine      (calibration.py)
  background thread  pygame       homography +
  MOG2 subtraction   synth tones  key regions
        │
        ▼
  Camera (OpenCV VideoCapture)
```

**Key design choices:**
- MJPEG over WebSocket for video: simpler, works in any `<img>` tag, zero extra JS libs
- MOG2 background subtraction: robust, no ML dependencies, trivially swappable
- Homography (perspective transform): maps the angled floor view to top-down normalised space so key detection is resolution-independent
- pygame.mixer with additive synthesis: cross-platform, low-latency, real sample files can be dropped in without code changes

---

## Project Structure

```
floor-piano/
├── run.py                  # Entry point
├── requirements.txt
├── config/
│   └── defaults.json       # Default settings (not modified at runtime)
├── data/                   # Runtime data (auto-created)
│   ├── calibration.json    # Saved calibration
│   └── settings.json       # Saved user settings
├── audio/
│   └── samples/            # Drop <NoteName>.wav files here (e.g. C4.wav)
├── backend/
│   ├── server.py           # FastAPI app, routing, WebSocket hub
│   ├── cv_pipeline.py      # Camera thread + MOG2 detection
│   ├── calibration.py      # Homography + key region math
│   ├── note_mapper.py      # Key index → note name/frequency
│   ├── audio_engine.py     # pygame-based playback + tone synthesis
│   └── config_manager.py   # JSON load/save for settings & calibration
└── frontend/
    ├── index.html
    ├── css/style.css
    └── js/app.js           # WebSocket client, calibration canvas, UI logic
```

---

## Installation

### Prerequisites

- Python 3.9 or newer
- A webcam (USB or built-in), or an RTSP/HTTP video stream URL
- On Linux: `sudo apt install libportaudio2` may be needed for pygame audio

### Steps

```bash
# 1. Clone / enter the project directory
cd floor-piano

# 2. Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python run.py
```

Open **http://127.0.0.1:8000** in your browser.

### Options

```
python run.py --host 0.0.0.0 --port 8080   # expose to local network
python run.py --reload                      # dev mode: auto-reload on changes
```

---

## Running the App

1. `python run.py`
2. Open **http://127.0.0.1:8000**
3. You should see the live camera feed in the left panel.
4. Follow the **Calibration Workflow** below.
5. Click **▶ Start** detection, wait 2–3 s for background to stabilise.
6. Step on the floor region — notes play and keys light up.

---

## Calibration Workflow

Calibration teaches the system which floor area maps to which piano keys.

### Step-by-step

1. **Position the camera** so the floor piano area is fully visible.
   A top-down or ~45° angle both work; the perspective transform will correct it.

2. **Click "Calibrate"** in the toolbar below the video.
   The video container gets an orange outline indicating calibration mode is active.

3. **Click 4 corners** of the floor piano region directly on the video image.
   Click them in order: **top-left → top-right → bottom-right → bottom-left**.
   (If you click out of order, drag the numbered handles to adjust.)

4. **Set the number of keys** in the "Keys" input (default 8 = one octave C4–C5).

5. **Drag handles** to fine-tune corner positions.
   The blue key divider lines give a live preview of how the area will be split.

6. **Click "Save Calibration"** — the data is sent to the server and persisted to
   `data/calibration.json` so it survives restarts.

7. **Exit calibration mode** automatically happens on save.
   The Python backend will now draw the key grid on every video frame.

### Re-calibrating

Click "Calibrate" again at any time. Existing points are not pre-loaded (you
start fresh) but the old calibration stays active on the server until you save
new points.

To erase calibration entirely, click **"Delete Calibration"**.

---

## Detection Settings

| Setting | Description | Default |
|---|---|---|
| Camera source | Webcam index (`0`, `1`, …) or stream URL | `0` |
| Sensitivity | 0–100. Higher = triggers on smaller movements | `60` |
| Cooldown | Milliseconds before the same key can trigger again | `400` |
| Min blob area | Minimum foreground blob size in pixels² (filters noise) | `800` |

**Tip:** If detection is too jittery, reduce sensitivity or increase cooldown.
If steps are being missed, increase sensitivity or reduce min blob area.

---

## Adding Real Piano Samples

Place `.wav` files named exactly like the note (e.g. `C4.wav`, `Db4.wav`) in
`audio/samples/`. The audio engine checks for these first and falls back to the
synthesised tone only if the file is missing.

Compatible note names: `C3 Db3 D3 Eb3 E3 F3 Gb3 G3 Ab3 A3 Bb3 B3`
and `C4 … B4`, `C5`.

Free piano sample packs (check licences before use):
- [University of Iowa Electronic Music Studios](https://theremin.music.uiowa.edu/MISpiano.html)
- [Salamander Grand Piano](https://freepats.zenvoid.org/Piano/acoustic-grand-piano.html)

---

## API Reference

| Method | Path | Description |
|---|---|---|
| GET | `/` | Serve the UI |
| GET | `/video_feed` | MJPEG camera stream |
| WS | `/ws` | Real-time event stream |
| GET | `/api/state` | Full server state snapshot |
| GET | `/api/calibration` | Current calibration data |
| POST | `/api/calibration` | Save calibration `{region_points, num_keys}` |
| DELETE | `/api/calibration` | Clear calibration |
| GET | `/api/settings` | Current settings |
| POST | `/api/settings` | Update settings |
| POST | `/api/detection/start` | Enable detection |
| POST | `/api/detection/stop` | Disable detection |
| POST | `/api/detection/reset_background` | Reset MOG2 model |

---

## Troubleshooting

**Camera feed is black / "Waiting for camera…"**
- Check that your webcam is connected and not used by another app.
- Try changing "Camera source" to `1` or `2` in Settings and click Apply.
- For IP/USB cameras, paste the full URL (e.g. `http://192.168.1.x/video`).

**No audio**
- On Linux, ensure `pulseaudio` or `pipewire` is running.
- Check that no other app has exclusive audio access.
- The terminal will show `[Audio] Init failed` if pygame.mixer could not open the device.

**Detection fires constantly even without movement**
- The background model hasn't stabilised. Click "Reset Background Model".
- Reduce Sensitivity.
- Make sure the camera is stable (no vibration, wind, changing light).

**Detection misses steps**
- Increase Sensitivity or reduce Min blob area.
- Ensure the calibrated region covers the whole floor piano area.
- Avoid wearing shoes that match the floor colour.

**Calibration points are in the wrong place**
- The canvas overlays the video 1:1. If the video is scaled in your browser,
  the scaling is accounted for automatically.
- Re-enter calibration mode and click / drag points to correct positions.

**`ModuleNotFoundError`**
- Make sure you activated your virtual environment before running.
- Re-run `pip install -r requirements.txt`.

---

## Future Improvements

1. **Pose estimation** — swap MOG2 for a foot-specific model (MediaPipe Pose, YOLOv8-pose) for single-frame detection accuracy independent of background learning time.
2. **MIDI output** — add `python-rtmidi` to emit real MIDI events so any DAW/synthesiser can receive them.
3. **Multi-player** — extend key cooldown to be per-session so two people can play simultaneously.
4. **Custom note mapping UI** — allow drag-and-drop reordering of keys and manual note assignment in the browser.
5. **Projection mapping** — integrate with a projector homography so the projected piano image stays aligned with the calibrated region automatically.
6. **WebRTC video** — replace MJPEG with a proper WebRTC track for lower latency on the browser side.
7. **Octave selection** — UI buttons to shift the note map up/down an octave.
8. **Velocity sensitivity** — use blob area or optical flow magnitude as a proxy for strike velocity and adjust volume accordingly.
9. **Record & playback** — log triggered notes with timestamps for simple loop recording.
10. **Docker container** — package the whole app for one-command deployment without manual Python setup.
