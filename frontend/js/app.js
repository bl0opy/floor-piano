/**
 * Floor Piano — frontend application
 *
 * Responsibilities:
 *  - Maintain a WebSocket connection to /ws for real-time events
 *  - Render interactive calibration overlay on the canvas
 *  - Send calibration / settings to the REST API
 *  - Reflect server state in the UI (detection on/off, active key, etc.)
 */

'use strict';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API = {
  state:           '/api/state',
  calibration:     '/api/calibration',
  settings:        '/api/settings',
  detectStart:     '/api/detection/start',
  detectStop:      '/api/detection/stop',
  resetBg:         '/api/detection/reset_background',
};

const CAL_POINT_RADIUS = 7;   // canvas px
const CAL_DRAG_RADIUS  = 16;  // hit area for dragging an existing point

// Canvas drawing colours
const C = {
  point:      '#f0a832',
  pointFill:  'rgba(240,168,50,0.25)',
  poly:       'rgba(79,142,247,0.20)',
  polyBorder: '#4f8ef7',
  line:       '#4f8ef7',
};

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const state = {
  wsConnected: false,
  detecting:   false,
  calibrated:  false,
  calMode:     false,
  numKeys:     8,
  calPoints:   [],          // [{x,y}] in canvas space (max 4)
  dragIndex:   -1,
  videoW:      640,         // actual camera resolution (from server)
  videoH:      480,
  notes:       [],
  activeKey:   null,
  activeKeyTmr: null,
};

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const $ = id => document.getElementById(id);

const videoFeed         = $('video-feed');
const canvas            = $('overlay-canvas');
const ctx               = canvas.getContext('2d');
const keyPop            = $('key-pop');
const wsStatus          = $('ws-status');
const activeKeyDisplay  = $('active-key-display');
const activeNoteDisplay = $('active-note-display');
const keyMap            = $('key-map');
const numKeysInput      = $('num-keys');
const calHint           = $('cal-hint');

// Buttons
const btnCalToggle  = $('btn-cal-toggle');
const btnCalClear   = $('btn-cal-clear');
const btnCalSave    = $('btn-cal-save');
const btnCalDelete  = $('btn-cal-delete');
const btnDetStart   = $('btn-detect-start');
const btnDetStop    = $('btn-detect-stop');
const btnResetBg    = $('btn-reset-bg');
const btnSaveSettings = $('btn-save-settings');

// Settings inputs
const settingCamera      = $('setting-camera');
const settingSensitivity = $('setting-sensitivity');
const settingCooldown    = $('setting-cooldown');
const settingBlob        = $('setting-blob');
const settingPolyphony   = $('setting-polyphony');
const settingFlip        = $('setting-flip');

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------

let ws = null;
let wsReconnectDelay = 1000;

function connectWS() {
  const url = `ws://${location.host}/ws`;
  ws = new WebSocket(url);

  ws.onopen = () => {
    state.wsConnected = true;
    wsReconnectDelay = 1000;
    setWsStatus(true);
    console.log('[WS] Connected');
  };

  ws.onclose = () => {
    state.wsConnected = false;
    setWsStatus(false);
    console.log(`[WS] Closed — reconnecting in ${wsReconnectDelay}ms`);
    setTimeout(connectWS, wsReconnectDelay);
    wsReconnectDelay = Math.min(wsReconnectDelay * 2, 8000);
  };

  ws.onerror = err => {
    console.warn('[WS] Error:', err);
    ws.close();
  };

  ws.onmessage = ev => {
    try {
      handleServerEvent(JSON.parse(ev.data));
    } catch (e) {
      console.warn('[WS] Bad message:', e);
    }
  };
}

function setWsStatus(ok) {
  wsStatus.textContent = ok ? 'Connected' : 'Disconnected';
  wsStatus.className = 'badge ' + (ok ? 'badge-ok' : 'badge-off');
}

// Heartbeat so the server can detect dead connections
setInterval(() => {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({type: 'ping'}));
}, 20000);

// ---------------------------------------------------------------------------
// Server event handler
// ---------------------------------------------------------------------------

function handleServerEvent(msg) {
  switch (msg.type) {

    case 'state':
      // Full snapshot on first connect / reconnect
      state.detecting  = msg.detection_enabled || false;
      state.calibrated = msg.calibrated || false;
      state.numKeys    = msg.num_keys || 8;
      state.videoW     = msg.frame_width  || 640;
      state.videoH     = msg.frame_height || 480;
      state.notes      = msg.notes || [];
      applySettingsToUI(msg.settings || {});
      numKeysInput.value = state.numKeys;
      renderKeyMap();
      updateDetectionButtons();
      updateCalHint();
      break;

    case 'key_triggered':
      showKeyTriggered(msg.key_index, msg.note_label);
      break;

    case 'detection_state':
      state.detecting = msg.enabled;
      updateDetectionButtons();
      break;

    case 'calibration_updated':
      state.calibrated = msg.calibrated;
      state.numKeys    = msg.num_keys || state.numKeys;
      state.notes      = msg.notes || state.notes;
      numKeysInput.value = state.numKeys;
      renderKeyMap();
      updateCalHint();
      drawCalOverlay();
      break;
  }
}

// ---------------------------------------------------------------------------
// Key trigger display
// ---------------------------------------------------------------------------

function showKeyTriggered(keyIndex, noteLabel) {
  // Update big displays
  activeKeyDisplay.textContent = noteLabel || `Key ${keyIndex + 1}`;
  activeNoteDisplay.textContent = `Key ${keyIndex + 1}`;
  activeKeyDisplay.style.color = '#4f8ef7';

  // Float pop-up on the video
  keyPop.textContent = noteLabel || `♪${keyIndex + 1}`;
  keyPop.classList.remove('hidden');

  // Highlight chip in the key map
  document.querySelectorAll('.key-chip').forEach((chip, i) => {
    chip.classList.toggle('active', i === keyIndex);
  });

  // Auto-dismiss
  clearTimeout(state.activeKeyTmr);
  state.activeKeyTmr = setTimeout(() => {
    keyPop.classList.add('hidden');
    document.querySelectorAll('.key-chip').forEach(c => c.classList.remove('active'));
    activeKeyDisplay.style.color = '';
  }, 600);
}

// ---------------------------------------------------------------------------
// Key map strip
// ---------------------------------------------------------------------------

function renderKeyMap() {
  keyMap.innerHTML = '';
  const n = state.numKeys || 8;
  for (let i = 0; i < n; i++) {
    const note = state.notes[i] || {};
    const chip = document.createElement('div');
    chip.className = 'key-chip';
    chip.dataset.key = i;
    chip.innerHTML = `<span class="chip-num">${i + 1}</span>${note.label || '—'}`;
    keyMap.appendChild(chip);
  }
}

// ---------------------------------------------------------------------------
// Detection button state
// ---------------------------------------------------------------------------

function updateDetectionButtons() {
  btnDetStart.disabled = state.detecting;
  btnDetStop.disabled  = !state.detecting;
}

// ---------------------------------------------------------------------------
// Calibration mode toggle
// ---------------------------------------------------------------------------

function enterCalMode() {
  state.calMode = true;
  document.body.classList.add('cal-mode');
  btnCalToggle.textContent = '✕ Exit Calibration';
  btnCalToggle.classList.replace('btn-primary', 'btn-warn');
  updateCalHint();
  drawCalOverlay();
}

function exitCalMode() {
  state.calMode = false;
  document.body.classList.remove('cal-mode');
  btnCalToggle.textContent = 'Calibrate';
  btnCalToggle.classList.replace('btn-warn', 'btn-primary');
  updateCalHint();
  drawCalOverlay();
}

function updateCalHint() {
  const n = state.calPoints.length;
  if (!state.calMode) {
    calHint.textContent = state.calibrated
      ? '✓ Floor region calibrated. Click Calibrate to edit.'
      : 'Click Calibrate, then click 4 corners of the floor piano region.';
    return;
  }
  if (n < 4) {
    calHint.textContent = `Click corner ${n + 1} of 4 on the video (top-left → top-right → bottom-right → bottom-left).`;
  } else {
    calHint.textContent = 'All 4 points set. Drag to adjust, then click Save Calibration.';
  }
  btnCalSave.disabled = n < 4;
}

// ---------------------------------------------------------------------------
// Canvas ↔ video coordinate conversion
// ---------------------------------------------------------------------------

function syncCanvas() {
  const rect = videoFeed.getBoundingClientRect();
  canvas.width  = rect.width  || 640;
  canvas.height = rect.height || 480;
}

function canvasToVideo(cx, cy) {
  return {
    x: Math.round(cx / canvas.width  * state.videoW),
    y: Math.round(cy / canvas.height * state.videoH),
  };
}

function videoToCanvas(vx, vy) {
  return {
    x: vx / state.videoW * canvas.width,
    y: vy / state.videoH * canvas.height,
  };
}

// ---------------------------------------------------------------------------
// Canvas drawing
// ---------------------------------------------------------------------------

function drawCalOverlay() {
  syncCanvas();
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const pts = state.calPoints;
  if (pts.length === 0) return;

  // Polygon fill
  if (pts.length === 4) {
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
    ctx.closePath();
    ctx.fillStyle = C.poly;
    ctx.fill();
    ctx.strokeStyle = C.polyBorder;
    ctx.lineWidth = 2;
    ctx.stroke();

    // Draw key divisions
    if (state.calMode) drawKeyDivisions(pts);
  } else {
    // Partial polygon: just lines between points
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
    ctx.strokeStyle = C.line;
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Draw point handles
  pts.forEach((p, i) => {
    ctx.beginPath();
    ctx.arc(p.x, p.y, CAL_POINT_RADIUS + 3, 0, Math.PI * 2);
    ctx.fillStyle = C.pointFill;
    ctx.fill();

    ctx.beginPath();
    ctx.arc(p.x, p.y, CAL_POINT_RADIUS, 0, Math.PI * 2);
    ctx.fillStyle = C.point;
    ctx.fill();

    ctx.fillStyle = '#111';
    ctx.font = 'bold 9px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(i + 1, p.x, p.y);
  });
}

/**
 * Draw evenly-spaced vertical key dividers inside the calibrated quad.
 * Uses bilinear interpolation between the four corners.
 */
function drawKeyDivisions(pts) {
  const n = parseInt(numKeysInput.value, 10) || state.numKeys;
  ctx.strokeStyle = 'rgba(255,255,255,0.35)';
  ctx.lineWidth = 1;

  // pts order: TL, TR, BR, BL
  const [tl, tr, br, bl] = pts;

  for (let i = 1; i < n; i++) {
    const t = i / n;
    // Linear interpolation along top and bottom edges
    const topX    = tl.x + (tr.x - tl.x) * t;
    const topY    = tl.y + (tr.y - tl.y) * t;
    const bottomX = bl.x + (br.x - bl.x) * t;
    const bottomY = bl.y + (br.y - bl.y) * t;

    ctx.beginPath();
    ctx.moveTo(topX, topY);
    ctx.lineTo(bottomX, bottomY);
    ctx.stroke();
  }
}

// ---------------------------------------------------------------------------
// Canvas mouse events (calibration)
// ---------------------------------------------------------------------------

function canvasMousePos(ev) {
  const rect = canvas.getBoundingClientRect();
  return { x: ev.clientX - rect.left, y: ev.clientY - rect.top };
}

function nearestPointIndex(pos) {
  for (let i = 0; i < state.calPoints.length; i++) {
    const p = state.calPoints[i];
    const d = Math.hypot(p.x - pos.x, p.y - pos.y);
    if (d <= CAL_DRAG_RADIUS) return i;
  }
  return -1;
}

canvas.addEventListener('mousedown', ev => {
  if (!state.calMode) return;
  const pos = canvasMousePos(ev);

  // Try to start dragging an existing point
  const idx = nearestPointIndex(pos);
  if (idx !== -1) {
    state.dragIndex = idx;
    return;
  }

  // Add new point (up to 4)
  if (state.calPoints.length < 4) {
    state.calPoints.push({ x: pos.x, y: pos.y });
    updateCalHint();
    drawCalOverlay();
  }
});

canvas.addEventListener('mousemove', ev => {
  if (!state.calMode || state.dragIndex === -1) return;
  const pos = canvasMousePos(ev);
  state.calPoints[state.dragIndex] = { x: pos.x, y: pos.y };
  drawCalOverlay();
});

canvas.addEventListener('mouseup', () => {
  state.dragIndex = -1;
});

canvas.addEventListener('mouseleave', () => {
  state.dragIndex = -1;
});

// ---------------------------------------------------------------------------
// Settings helpers
// ---------------------------------------------------------------------------

function applySettingsToUI(s) {
  if (s.camera_source !== undefined) settingCamera.value = s.camera_source;
  if (s.sensitivity   !== undefined) {
    settingSensitivity.value      = s.sensitivity;
    $('val-sensitivity').textContent = s.sensitivity;
  }
  if (s.cooldown_ms !== undefined) {
    settingCooldown.value          = s.cooldown_ms;
    $('val-cooldown').textContent  = s.cooldown_ms;
  }
  if (s.min_blob_area !== undefined) {
    settingBlob.value              = s.min_blob_area;
    $('val-blob').textContent      = s.min_blob_area;
  }
  if (s.polyphony_limit !== undefined) settingPolyphony.value = s.polyphony_limit;
  if (s.flip_horizontal !== undefined) settingFlip.checked = !!s.flip_horizontal;
}

// Live-update slider labels
settingSensitivity.addEventListener('input', () => {
  $('val-sensitivity').textContent = settingSensitivity.value;
});
settingCooldown.addEventListener('input', () => {
  $('val-cooldown').textContent = settingCooldown.value;
});
settingBlob.addEventListener('input', () => {
  $('val-blob').textContent = settingBlob.value;
});

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function post(url, body) {
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return res.ok ? res.json() : null;
  } catch (e) {
    console.error('POST', url, e);
    return null;
  }
}

async function del(url) {
  try {
    const res = await fetch(url, { method: 'DELETE' });
    return res.ok ? res.json() : null;
  } catch (e) {
    console.error('DELETE', url, e);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Button handlers
// ---------------------------------------------------------------------------

btnCalToggle.addEventListener('click', () => {
  state.calMode ? exitCalMode() : enterCalMode();
});

btnCalClear.addEventListener('click', () => {
  state.calPoints = [];
  btnCalSave.disabled = true;
  drawCalOverlay();
  updateCalHint();
});

btnCalSave.addEventListener('click', async () => {
  if (state.calPoints.length !== 4) return;

  // Convert canvas coords → video coords
  const videoPoints = state.calPoints.map(p => {
    const v = canvasToVideo(p.x, p.y);
    return [v.x, v.y];
  });

  const numKeys = Math.max(1, parseInt(numKeysInput.value, 10) || 8);
  const result = await post(API.calibration, { region_points: videoPoints, num_keys: numKeys });

  if (result?.success) {
    state.calibrated = true;
    state.numKeys    = numKeys;
    exitCalMode();
    // Keep the drawn points so user can see what was saved
    drawCalOverlay();
  } else {
    alert('Calibration save failed. Make sure you have exactly 4 points.');
  }
});

btnCalDelete.addEventListener('click', async () => {
  if (!confirm('Delete calibration data?')) return;
  await del(API.calibration);
  state.calibrated = false;
  state.calPoints  = [];
  drawCalOverlay();
  updateCalHint();
});

btnDetStart.addEventListener('click', async () => {
  await post(API.detectStart, {});
  state.detecting = true;
  updateDetectionButtons();
});

btnDetStop.addEventListener('click', async () => {
  await post(API.detectStop, {});
  state.detecting = false;
  updateDetectionButtons();
});

btnResetBg.addEventListener('click', () => post(API.resetBg, {}));

btnSaveSettings.addEventListener('click', async () => {
  const src = settingCamera.value.trim();
  await post(API.settings, {
    camera_source: /^\d+$/.test(src) ? parseInt(src, 10) : src,
    sensitivity:     parseInt(settingSensitivity.value, 10),
    cooldown_ms:     parseInt(settingCooldown.value, 10),
    min_blob_area:   parseInt(settingBlob.value, 10),
    polyphony_limit: Math.max(1, parseInt(settingPolyphony.value, 10) || 2),
    flip_horizontal: settingFlip.checked,
  });
});

// ---------------------------------------------------------------------------
// Initial load
// ---------------------------------------------------------------------------

async function loadInitialState() {
  try {
    const data = await fetch(API.state).then(r => r.json());

    state.detecting  = data.detection_enabled || false;
    state.calibrated = data.calibrated        || false;
    state.numKeys    = data.num_keys          || 8;
    state.videoW     = data.frame_width       || 640;
    state.videoH     = data.frame_height      || 480;
    state.notes      = data.notes             || [];

    numKeysInput.value = state.numKeys;
    applySettingsToUI(data.settings || {});
    renderKeyMap();
    updateDetectionButtons();
    updateCalHint();
  } catch (e) {
    console.warn('Could not load initial state:', e);
  }
}

// ---------------------------------------------------------------------------
// Handle video-feed img load / resize
// ---------------------------------------------------------------------------

videoFeed.addEventListener('load', () => {
  syncCanvas();
  drawCalOverlay();
});

// Reload MJPEG on error (e.g. server restart)
videoFeed.addEventListener('error', () => {
  setTimeout(() => { videoFeed.src = '/video_feed?' + Date.now(); }, 2000);
});

window.addEventListener('resize', () => {
  syncCanvas();
  drawCalOverlay();
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

connectWS();
loadInitialState();
