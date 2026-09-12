/* Event Crowd Monitor — dashboard logic.
   Uses lightweight polling (1s for status, 2s for events) rather than
   WebSockets, matching the "reliable polling fallback" allowed by spec
   section 16. Simple to reason about and robust to a camera dropping. */

const STATUS_POLL_MS = 1000;
const EVENTS_POLL_MS = 2000;

const cameraGrid = document.getElementById("camera-grid");
const activityList = document.getElementById("activity-list");
const sessionLabel = document.getElementById("session-label");
const toast = document.getElementById("toast");

let knownCameraIds = new Set();
let lastEventId = null;

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("toast--visible");
  setTimeout(() => toast.classList.remove("toast--visible"), 2200);
}

function ensureCameraPanel(cam) {
  if (knownCameraIds.has(cam.camera_id)) return;
  knownCameraIds.add(cam.camera_id);

  const panel = document.createElement("article");
  panel.className = "camera-panel";
  panel.id = `panel-${cam.camera_id}`;
  panel.innerHTML = `
    <div class="camera-panel__head">
      <span class="camera-panel__name">${cam.name}</span>
      <span class="status-pill" data-status="${cam.status}">
        <span class="status-pill__dot"></span>
        <span class="status-pill__text">${cam.status}</span>
      </span>
    </div>
    <div class="camera-panel__video">
      ${cam.status === "OFFLINE"
        ? `<div class="camera-panel__video-empty">Camera offline —<br>no signal</div>`
        : `<img src="/video/${cam.camera_id}" alt="${cam.name} live feed">`}
    </div>
    <div class="camera-panel__stats">
      <div class="stat stat--live">
        <div class="stat__label">Live crowd</div>
        <div class="stat__value" data-field="live_occupancy">${cam.live_occupancy}</div>
      </div>
      <div class="stat">
        <div class="stat__label">Entry</div>
        <div class="stat__value" data-field="entries">${cam.entries}</div>
      </div>
      <div class="stat">
        <div class="stat__label">Exit</div>
        <div class="stat__value" data-field="exits">${cam.exits}</div>
      </div>
    </div>
  `;
  cameraGrid.appendChild(panel);
}

function updateCameraPanel(cam) {
  const panel = document.getElementById(`panel-${cam.camera_id}`);
  if (!panel) return;

  const pill = panel.querySelector(".status-pill");
  const prevStatus = pill.dataset.status;
  pill.dataset.status = cam.status;
  pill.querySelector(".status-pill__text").textContent = cam.status;

  // If a camera just came online (or offline), refresh the <img> src so
  // the MJPEG stream (re)connects cleanly rather than showing a stale frame.
  if (prevStatus !== cam.status) {
    const videoBox = panel.querySelector(".camera-panel__video");
    if (cam.status === "OFFLINE") {
      videoBox.innerHTML = `<div class="camera-panel__video-empty">Camera offline —<br>no signal</div>`;
    } else if (!videoBox.querySelector("img")) {
      videoBox.innerHTML = `<img src="/video/${cam.camera_id}?t=${Date.now()}" alt="${cam.name} live feed">`;
    }
  }

  panel.querySelector('[data-field="live_occupancy"]').textContent = cam.live_occupancy;
  panel.querySelector('[data-field="entries"]').textContent = cam.entries;
  panel.querySelector('[data-field="exits"]').textContent = cam.exits;
}

async function pollStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) throw new Error(`status ${res.status}`);
    const data = await res.json();
    for (const cam of data.cameras) {
      ensureCameraPanel(cam);
      updateCameraPanel(cam);
    }
    updateSummary(data.cameras);
  } catch (err) {
    console.error("status poll failed:", err);
  } finally {
    setTimeout(pollStatus, STATUS_POLL_MS);
  }
}

// "Total crowd inside event area" = event_entrance's live occupancy minus
// however many of those people have since walked into dining_entrance
// (each dining ENTRY means one fewer person in the main event area).
// "Total crowd entered in dining" = dining_entrance's cumulative entries.
// Both derived client-side from /api/status — no new endpoint needed, and
// this degrades gracefully (dining count = 0) if dining_entrance is
// disabled or absent from the response.
function updateSummary(cameras) {
  const eventCam = cameras.find((c) => c.camera_id === "event_entrance");
  const diningCam = cameras.find((c) => c.camera_id === "dining_entrance");
  const eventLive = eventCam ? eventCam.live_occupancy : 0;
  const diningEntries = diningCam ? diningCam.entries : 0;
  const totalInEventArea = Math.max(0, eventLive - diningEntries);

  const eventEl = document.getElementById("summary-event-total");
  const diningEl = document.getElementById("summary-dining-total");
  if (eventEl) eventEl.textContent = totalInEventArea;
  if (diningEl) diningEl.textContent = diningEntries;
}

function formatTime(unixSeconds) {
  const d = new Date(unixSeconds * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

async function pollEvents() {
  try {
    const res = await fetch("/api/events?limit=15");
    if (!res.ok) throw new Error(`events ${res.status}`);
    const data = await res.json();
    renderEvents(data.events);
  } catch (err) {
    console.error("events poll failed:", err);
  } finally {
    setTimeout(pollEvents, EVENTS_POLL_MS);
  }
}

function renderEvents(events) {
  if (!events || events.length === 0) {
    activityList.innerHTML = `<li class="activity__empty">No crossings recorded yet.</li>`;
    return;
  }

  if (events[0].id === lastEventId) return; // nothing new, skip re-render
  lastEventId = events[0].id;

  activityList.innerHTML = events
    .map((e) => {
      const badgeClass = e.event_type === "ENTRY" ? "event-badge--entry" : "event-badge--exit";
      return `
        <li>
          <span class="event-badge ${badgeClass}">${e.event_type}</span>
          <span class="activity__camera">${e.camera_id}</span>
          <span class="activity__time">${formatTime(e.timestamp)}</span>
        </li>`;
    })
    .join("");
}

document.getElementById("reset-btn").addEventListener("click", async () => {
  try {
    const res = await fetch("/api/reset", { method: "POST" });
    if (!res.ok) throw new Error(`reset ${res.status}`);
    showToast("Counters reset");
  } catch (err) {
    showToast("Reset failed — check server logs");
  }
});

document.getElementById("new-session-btn").addEventListener("click", async () => {
  try {
    const res = await fetch("/api/session/start", { method: "POST" });
    if (!res.ok) throw new Error(`session ${res.status}`);
    const data = await res.json();
    sessionLabel.textContent = `Session #${data.session_id}`;
    lastEventId = null;
    showToast("New session started");
  } catch (err) {
    showToast("Could not start a new session");
  }
});

pollStatus();
pollEvents();
