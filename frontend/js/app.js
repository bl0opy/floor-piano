/**
 * Floor Piano — multi-region frontend
 *
 * Up to 4 independent detection zones can be drawn on the canvas.
 * Each zone is a quadrilateral; the user picks one note per zone.
 */

'use strict';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API = {
  state:       '/api/state',
  calibration: '/api/calibration',
  settings:    '/api/settings',
  detectStart: '/api/detection/start',
  detectStop:  '/api/detection/stop',
  resetBg:     '/api/detection/reset_background',
};

const MAX_REGIONS = 4;
const REGION_COLORS   = ['#4f8ef7', '#34c27a', '#f0a832', '#e05252'];
const REGION_FILLS    = ['rgba(79,142,247,0.18)', 'rgba(52,194,122,0.18)',
                         'rgba(240,168,50,0.18)',  'rgba(224,82,82,0.18)'];
const DEFAULT_NOTES_PER_REGION = ['C4', 'G4', 'E4', 'A4'];

const DRAG_RADIUS = 16;   // px hit area for point dragging

// ---------------------------------------------------------------------------
// Note list (C2–C6 chromatic, generated on startup from server or built here)
// ---------------------------------------------------------------------------

let AVAILABLE_NOTES = [];   // [{name, frequency, label}, …] from server

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const state = {
  wsConnected:  false,
  detecting:    false,
  // Regions stored in VIDEO space: [{points:[[vx,vy]×4], note:"C4"}, …]
  regions:      [],
  // Index of the region currently being drawn; -1 = not drawing
  drawingIdx:   -1,
  // Video dimensions (from server)
  videoW: 640,
  videoH: 480,
  // Drag state: {regionIdx, pointIdx} or null
  dragInfo:     null,
  // Whether state.regions differs from last saved server state
  unsaved:      false,
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
const regionList        = $('region-list');
const regionCount       = $('region-count');
const regionEmptyHint   = $('region-empty-hint');
const calHint           = $('cal-hint');

const btnAddRegion   = $('btn-add-region');
const btnCancelDraw  = $('btn-cancel-draw');
const btnClearAll    = $('btn-clear-all');
const btnCalSave     = $('btn-cal-save');
const btnCalDelete   = $('btn-cal-delete');
const btnDetStart    = $('btn-detect-start');
const btnDetStop     = $('btn-detect-stop');
const btnResetBg     = $('btn-reset-bg');
const btnSaveSettings = $('btn-save-settings');

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
  };

  ws.onclose = () => {
    state.wsConnected = false;
    setWsStatus(false);
    setTimeout(connectWS, wsReconnectDelay);
    wsReconnectDelay = Math.min(wsReconnectDelay * 2, 8000);
  };

  ws.onerror = () => ws.close();

  ws.onmessage = ev => {
    try { handleServerEvent(JSON.parse(ev.data)); }
    catch (e) { console.warn('[WS] Bad message:', e); }
  };
}

function setWsStatus(ok) {
  wsStatus.textContent = ok ? 'Connected' : 'Disconnected';
  wsStatus.className = 'badge ' + (ok ? 'badge-ok' : 'badge-off');
}

setInterval(() => {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({type: 'ping'}));
}, 20000);

// ---------------------------------------------------------------------------
// Server event handler
// ---------------------------------------------------------------------------

function handleServerEvent(msg) {
  switch (msg.type) {

    case 'state':
      state.detecting = msg.detection_enabled || false;
      state.videoW    = msg.frame_width  || 640;
      state.videoH    = msg.frame_height || 480;
      if (msg.available_notes?.length) AVAILABLE_NOTES = msg.available_notes;
      if (msg.regions) {
        state.regions = msg.regions.map(r => ({points: r.points.map(p => [...p]), note: r.note}));
        state.unsaved = false;
      }
      applySettingsToUI(msg.settings || {});
      updateDetectionButtons();
      renderRegionList();
      drawRegionOverlay();
      updateToolbarState();
      break;

    case 'key_triggered':
      showNoteTriggered(msg.region_index, msg.note_label);
      break;

    case 'detection_state':
      state.detecting = msg.enabled;
      updateDetectionButtons();
      break;

    case 'calibration_updated':
      if (msg.regions) {
        state.regions = msg.regions.map(r => ({points: r.points.map(p => [...p]), note: r.note}));
        state.unsaved = false;
      } else if (!msg.calibrated) {
        state.regions = [];
        state.unsaved = false;
      }
      renderRegionList();
      drawRegionOverlay();
      updateToolbarState();
      break;
  }
}

// ---------------------------------------------------------------------------
// Note trigger display
// ---------------------------------------------------------------------------

function showNoteTriggered(regionIdx, noteLabel) {
  activeKeyDisplay.textContent = noteLabel || '?';
  activeNoteDisplay.textContent = `Region ${regionIdx + 1}`;
  const color = REGION_COLORS[regionIdx % REGION_COLORS.length];
  activeKeyDisplay.style.color = color;

  keyPop.textContent = noteLabel || '♪';
  keyPop.style.background = color + 'dd';
  keyPop.classList.remove('hidden');

  clearTimeout(state._popTimer);
  state._popTimer = setTimeout(() => {
    keyPop.classList.add('hidden');
    activeKeyDisplay.style.color = '';
  }, 600);
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
  return [
    Math.round(cx / canvas.width  * state.videoW),
    Math.round(cy / canvas.height * state.videoH),
  ];
}

function videoToCanvas(vx, vy) {
  return {
    x: vx / state.videoW * canvas.width,
    y: vy / state.videoH * canvas.height,
  };
}

// ---------------------------------------------------------------------------
// Canvas overlay drawing
// ---------------------------------------------------------------------------

function drawRegionOverlay() {
  syncCanvas();
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Draw saved / complete regions
  state.regions.forEach((region, idx) => {
    if (idx === state.drawingIdx) return;   // drawn separately below
    const pts = region.points.map(([vx, vy]) => videoToCanvas(vx, vy));
    if (pts.length === 4) drawCompleteRegion(pts, idx, region.note);
  });

  // Draw the region currently being drawn
  if (state.drawingIdx !== -1) {
    const region = state.regions[state.drawingIdx];
    if (region) {
      const pts = region.points.map(([vx, vy]) => videoToCanvas(vx, vy));
      drawInProgressRegion(pts, state.drawingIdx);
    }
  }
}

function drawCompleteRegion(pts, idx, note) {
  const color = REGION_COLORS[idx % REGION_COLORS.length];
  const fill  = REGION_FILLS[idx % REGION_FILLS.length];

  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  for (let i = 1; i < 4; i++) ctx.lineTo(pts[i].x, pts[i].y);
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.setLineDash([]);
  ctx.stroke();

  // Note label
  const cx = pts.reduce((s, p) => s + p.x, 0) / 4;
  const cy = pts.reduce((s, p) => s + p.y, 0) / 4;
  ctx.font = 'bold 15px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = color;
  ctx.fillText(note || '?', cx, cy);

  // Corner handles
  pts.forEach(p => drawHandle(p.x, p.y, color));
}

function drawInProgressRegion(pts, idx) {
  const color = REGION_COLORS[idx % REGION_COLORS.length];

  if (pts.length === 0) return;

  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.setLineDash([6, 4]);
  ctx.stroke();
  ctx.setLineDash([]);

  pts.forEach(p => drawHandle(p.x, p.y, color));
}

function drawHandle(x, y, color) {
  ctx.beginPath();
  ctx.arc(x, y, 9, 0, Math.PI * 2);
  ctx.fillStyle = color + '44';
  ctx.fill();
  ctx.beginPath();
  ctx.arc(x, y, 5, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
}

// ---------------------------------------------------------------------------
// Canvas mouse events
// ---------------------------------------------------------------------------

function canvasPos(ev) {
  const r = canvas.getBoundingClientRect();
  return { x: ev.clientX - r.left, y: ev.clientY - r.top };
}

/** Find nearest draggable point across all complete regions. Returns {regionIdx,pointIdx} or null. */
function findNearestPoint(pos) {
  let best = null, bestD = DRAG_RADIUS;
  state.regions.forEach((region, rIdx) => {
    if (region.points.length < 4) return;
    region.points.forEach(([vx, vy], pIdx) => {
      const cp = videoToCanvas(vx, vy);
      const d = Math.hypot(cp.x - pos.x, cp.y - pos.y);
      if (d < bestD) { bestD = d; best = { regionIdx: rIdx, pointIdx: pIdx }; }
    });
  });
  return best;
}

canvas.addEventListener('mousedown', ev => {
  const pos = canvasPos(ev);

  // Try dragging an existing point (any complete region)
  const hit = findNearestPoint(pos);
  if (hit) {
    state.dragInfo = hit;
    canvas.style.cursor = 'grabbing';
    return;
  }

  // Add point to the region being drawn
  if (state.drawingIdx !== -1) {
    const region = state.regions[state.drawingIdx];
    if (region && region.points.length < 4) {
      region.points.push(canvasToVideo(pos.x, pos.y));
      if (region.points.length === 4) {
        // Region complete — exit drawing mode
        state.drawingIdx = -1;
        state.unsaved = true;
        updateToolbarState();
        renderRegionList();
      }
      drawRegionOverlay();
      updateCalHint();
    }
  }
});

canvas.addEventListener('mousemove', ev => {
  const pos = canvasPos(ev);

  if (state.dragInfo) {
    const { regionIdx, pointIdx } = state.dragInfo;
    state.regions[regionIdx].points[pointIdx] = canvasToVideo(pos.x, pos.y);
    state.unsaved = true;
    drawRegionOverlay();
    return;
  }

  // Update cursor
  if (state.drawingIdx !== -1) {
    canvas.style.cursor = 'crosshair';
  } else if (findNearestPoint(pos)) {
    canvas.style.cursor = 'grab';
  } else {
    canvas.style.cursor = 'default';
  }
});

canvas.addEventListener('mouseup', () => {
  state.dragInfo = null;
  canvas.style.cursor = state.drawingIdx !== -1 ? 'crosshair' : 'default';
});

canvas.addEventListener('mouseleave', () => {
  state.dragInfo = null;
});

// ---------------------------------------------------------------------------
// Region management
// ---------------------------------------------------------------------------

function startAddRegion() {
  if (state.regions.length >= MAX_REGIONS) return;
  if (state.drawingIdx !== -1) return;  // already drawing

  const idx = state.regions.length;
  state.regions.push({ points: [], note: DEFAULT_NOTES_PER_REGION[idx] || 'C4' });
  state.drawingIdx = idx;

  canvas.style.pointerEvents = 'auto';
  canvas.style.cursor = 'crosshair';

  updateToolbarState();
  renderRegionList();
  updateCalHint();
  drawRegionOverlay();
}

function cancelDrawing() {
  if (state.drawingIdx === -1) return;
  state.regions.splice(state.drawingIdx, 1);
  state.drawingIdx = -1;
  canvas.style.cursor = 'default';
  updateToolbarState();
  renderRegionList();
  updateCalHint();
  drawRegionOverlay();
}

function deleteRegion(idx) {
  if (state.drawingIdx === idx) {
    state.drawingIdx = -1;
    canvas.style.cursor = 'default';
  } else if (state.drawingIdx > idx) {
    state.drawingIdx--;
  }
  state.regions.splice(idx, 1);
  state.unsaved = true;
  updateToolbarState();
  renderRegionList();
  updateCalHint();
  drawRegionOverlay();
}

function setRegionNote(idx, note) {
  if (state.regions[idx]) {
    state.regions[idx].note = note;
    state.unsaved = true;
    updateToolbarState();
    drawRegionOverlay();
  }
}

// ---------------------------------------------------------------------------
// Toolbar / button state
// ---------------------------------------------------------------------------

function updateToolbarState() {
  const drawing  = state.drawingIdx !== -1;
  const complete = state.regions.filter(r => r.points.length === 4);
  const canAdd   = !drawing && state.regions.length < MAX_REGIONS;

  btnAddRegion.disabled  = !canAdd;
  btnAddRegion.classList.toggle('hidden', drawing);
  btnCancelDraw.classList.toggle('hidden', !drawing);
  btnClearAll.disabled   = state.regions.length === 0;
  btnCalSave.disabled    = complete.length === 0 || drawing;

  regionCount.textContent = `${complete.length} / ${MAX_REGIONS}`;
}

function updateCalHint() {
  if (state.drawingIdx !== -1) {
    const region = state.regions[state.drawingIdx];
    const n = region ? region.points.length : 0;
    const remaining = 4 - n;
    calHint.textContent = remaining > 0
      ? `Click ${remaining} more corner${remaining > 1 ? 's' : ''} for Region ${state.drawingIdx + 1}.`
      : 'Region complete.';
    calHint.style.color = REGION_COLORS[state.drawingIdx % REGION_COLORS.length];
  } else if (state.unsaved && state.regions.some(r => r.points.length === 4)) {
    calHint.textContent = 'Unsaved changes — click "Save Regions" to apply.';
    calHint.style.color = '#f0a832';
  } else if (state.regions.some(r => r.points.length === 4)) {
    calHint.textContent = `✓ ${state.regions.filter(r => r.points.length === 4).length} region(s) saved. Drag corners to adjust, then Save.`;
    calHint.style.color = '';
  } else {
    calHint.textContent = 'Click "+ Add Region", then click 4 corners on the video to define a detection zone.';
    calHint.style.color = '';
  }
}

// ---------------------------------------------------------------------------
// Region list rendering
// ---------------------------------------------------------------------------

function renderRegionList() {
  const complete = state.regions.filter(r => r.points.length === 4);
  regionEmptyHint.style.display = state.regions.length === 0 ? '' : 'none';

  // Remove old region items (keep the empty hint)
  regionList.querySelectorAll('.region-item').forEach(el => el.remove());

  state.regions.forEach((region, idx) => {
    const color = REGION_COLORS[idx % REGION_COLORS.length];
    const isDrawing = idx === state.drawingIdx;
    const isComplete = region.points.length === 4;

    const item = document.createElement('div');
    item.className = 'region-item';
    item.dataset.idx = idx;

    // Colour swatch
    const swatch = document.createElement('div');
    swatch.className = 'region-swatch';
    swatch.style.background = color;

    // Label
    const label = document.createElement('span');
    label.className = 'region-label';
    label.textContent = `Region ${idx + 1}`;
    if (isDrawing) {
      label.textContent += ' — drawing…';
      label.style.color = color;
    }

    item.appendChild(swatch);
    item.appendChild(label);

    if (isComplete) {
      // Note selector
      const sel = document.createElement('select');
      sel.className = 'note-select';
      sel.title = 'Note to play when this region is triggered';
      AVAILABLE_NOTES.forEach(n => {
        const opt = document.createElement('option');
        opt.value = n.name;
        opt.textContent = n.label;
        if (n.name === region.note) opt.selected = true;
        sel.appendChild(opt);
      });
      sel.addEventListener('change', () => setRegionNote(idx, sel.value));
      item.appendChild(sel);
    }

    // Delete button
    const del = document.createElement('button');
    del.className = 'btn btn-danger btn-xs';
    del.textContent = '×';
    del.title = 'Remove region';
    del.addEventListener('click', () => deleteRegion(idx));
    item.appendChild(del);

    regionList.appendChild(item);
  });

  updateCalHint();
}

// ---------------------------------------------------------------------------
// Settings helpers
// ---------------------------------------------------------------------------

function applySettingsToUI(s) {
  if (s.camera_source !== undefined) settingCamera.value = s.camera_source;
  if (s.sensitivity   !== undefined) {
    settingSensitivity.value = s.sensitivity;
    $('val-sensitivity').textContent = s.sensitivity;
  }
  if (s.cooldown_ms !== undefined) {
    settingCooldown.value = s.cooldown_ms;
    $('val-cooldown').textContent = s.cooldown_ms;
  }
  if (s.min_blob_area !== undefined) {
    settingBlob.value = s.min_blob_area;
    $('val-blob').textContent = s.min_blob_area;
  }
  if (s.polyphony_limit !== undefined) settingPolyphony.value = s.polyphony_limit;
  if (s.flip_horizontal !== undefined) settingFlip.checked = !!s.flip_horizontal;
}

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
// Detection button state
// ---------------------------------------------------------------------------

function updateDetectionButtons() {
  btnDetStart.disabled = state.detecting;
  btnDetStop.disabled  = !state.detecting;
}

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

btnAddRegion.addEventListener('click', startAddRegion);
btnCancelDraw.addEventListener('click', cancelDrawing);

btnClearAll.addEventListener('click', () => {
  if (state.regions.length === 0) return;
  state.regions = [];
  state.drawingIdx = -1;
  state.unsaved = true;
  canvas.style.cursor = 'default';
  updateToolbarState();
  renderRegionList();
  drawRegionOverlay();
  updateCalHint();
});

btnCalSave.addEventListener('click', async () => {
  const complete = state.regions.filter(r => r.points.length === 4);
  if (complete.length === 0) return;

  const payload = {
    regions: complete.map(r => ({
      points: r.points,
      note: r.note,
    })),
  };

  const result = await post(API.calibration, payload);
  if (result?.success) {
    state.unsaved = false;
    // Server will broadcast calibration_updated; update hint immediately
    updateCalHint();
  } else {
    alert('Failed to save regions. Check that each region has exactly 4 points.');
  }
});

btnCalDelete.addEventListener('click', async () => {
  if (!confirm('Delete all saved calibration data?')) return;
  await del(API.calibration);
  state.regions = [];
  state.drawingIdx = -1;
  state.unsaved = false;
  canvas.style.cursor = 'default';
  updateToolbarState();
  renderRegionList();
  drawRegionOverlay();
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
    camera_source:   /^\d+$/.test(src) ? parseInt(src, 10) : src,
    sensitivity:     parseInt(settingSensitivity.value, 10),
    cooldown_ms:     parseInt(settingCooldown.value, 10),
    min_blob_area:   parseInt(settingBlob.value, 10),
    polyphony_limit: Math.max(1, parseInt(settingPolyphony.value, 10) || 4),
    flip_horizontal: settingFlip.checked,
  });
});

// ---------------------------------------------------------------------------
// Initial load
// ---------------------------------------------------------------------------

async function loadInitialState() {
  try {
    const data = await fetch(API.state).then(r => r.json());

    state.detecting = data.detection_enabled || false;
    state.videoW    = data.frame_width  || 640;
    state.videoH    = data.frame_height || 480;

    if (data.available_notes?.length) AVAILABLE_NOTES = data.available_notes;
    if (data.regions) {
      state.regions = data.regions.map(r => ({
        points: r.points.map(p => [...p]),
        note: r.note,
      }));
    }

    applySettingsToUI(data.settings || {});
    updateDetectionButtons();
    updateToolbarState();
    renderRegionList();
    drawRegionOverlay();
    updateCalHint();
  } catch (e) {
    console.warn('Could not load initial state:', e);
  }
}

// ---------------------------------------------------------------------------
// Video feed event handlers
// ---------------------------------------------------------------------------

videoFeed.addEventListener('load', () => {
  syncCanvas();
  drawRegionOverlay();
});

videoFeed.addEventListener('error', () => {
  setTimeout(() => { videoFeed.src = '/video_feed?' + Date.now(); }, 2000);
});

window.addEventListener('resize', () => {
  syncCanvas();
  drawRegionOverlay();
});

// Canvas is always interactive (pointer-events managed via JS)
canvas.style.pointerEvents = 'auto';

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

connectWS();
loadInitialState();
