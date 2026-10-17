const $ = (id) => document.getElementById(id);
const ui = {
  count: $("count"), status: $("sensor-status"), label: $("connection-label"),
  error: $("connection-error"), feed: $("activity-list"), reading: $("reading"),
  zone: $("zone-visual"), pill: $("status-pill"), session: $("session-id"),
  address: $("phone-address"), connect: $("connect-button"), disconnect: $("disconnect-button"),
};
let total = 0;
let isNear = null;
let hasBaseline = false;
let nearSince = 0;
let lastCountAt = 0;
const seenEvents = new Set();
let toastTimer;

function toast(message) {
  const element = $("toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove("show"), 2400);
}

function setCount(value) {
  total = Math.max(0, value);
  ui.count.textContent = String(total).padStart(2, "0");
}

function addActivity(message, detail = "") {
  const empty = ui.feed.querySelector(".empty-state");
  if (empty) empty.remove();
  const row = document.createElement("div");
  row.className = "activity-item";
  const marker = document.createElement("span");
  marker.className = "activity-mark";
  marker.textContent = "↗";
  const text = document.createElement("span");
  text.innerHTML = `${message}${detail ? ` <strong>${detail}</strong>` : ""}`;
  const time = document.createElement("time");
  time.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  row.append(marker, text, time);
  ui.feed.prepend(row);
  while (ui.feed.children.length > 6) ui.feed.lastElementChild.remove();
}

function connectionState(connected, status) {
  const online = connected === true;
  $("top-status").textContent = online ? "CONNECTED" : (status || "OFFLINE").toUpperCase();
  $("top-indicator").classList.toggle("live", online);
  $("sensor-led").classList.toggle("live", online);
  ui.label.classList.toggle("connected", online);
  ui.label.querySelector("span").textContent = status || (online ? "Connected" : "Not connected");
  const connecting = status === "Connecting…";
  ui.connect.classList.toggle("hidden", connecting);
  ui.disconnect.classList.toggle("hidden", !online && !connecting);
  ui.connect.disabled = connecting;
  ui.connect.innerHTML = online ? '<span class="button-icon">↻</span> Update connection' : '<span class="button-icon">↗</span> Connect phone';
  $("connection-error").classList.add("hidden");
}

function toObject(value) {
  if (!value) return {};
  if (typeof value === "object") return value;
  if (typeof value === "string") {
    try { return JSON.parse(value); } catch { return {}; }
  }
  return {};
}

function findProximity(payload) {
  let root = toObject(payload);
  for (let depth = 0; depth < 5; depth++) {
    const entries = Object.entries(root);
    const match = entries.find(([key]) => /^(proximity|prox|distance|near)$/i.test(key));
    if (match) return { found: true, value: match[1], key: match[0] };
    const sensorKey = entries.find(([key]) => /^(sensor|name|type)$/i.test(key));
    if (sensorKey && /proximity/i.test(String(sensorKey[1]))) {
      for (const [key, value] of entries) {
        if (/^(value|distance|reading|near)$/i.test(key)) return { found: true, value, key };
      }
      const nested = entries.find(([key, value]) => /^(data|values|reading)$/i.test(key) && typeof value === "object");
      if (nested) { root = toObject(nested[1]); continue; }
    }
    const nested = entries.find(([key, value]) => /^(data|payload|values|sensors)$/i.test(key) && typeof value === "object");
    if (!nested) break;
    root = toObject(nested[1]);
  }
  return { found: false };
}

function normalizeReading(raw) {
  if (typeof raw === "boolean") return { near: raw, display: raw ? "NEAR" : "FAR", numeric: raw ? 0 : null };
  if (typeof raw === "string") {
    if (/^(near|close|present)$/i.test(raw)) return { near: true, display: raw.toUpperCase(), numeric: 0 };
    if (/^(far|away|clear)$/i.test(raw)) return { near: false, display: raw.toUpperCase(), numeric: null };
    const parsed = Number(raw);
    if (Number.isFinite(parsed)) raw = parsed;
    else return null;
  }
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return { near: raw <= Number($("threshold").value), display: `${raw.toFixed(2)} cm`, numeric: raw };
  }
  if (raw && typeof raw === "object") {
    if (typeof raw.near === "boolean") return normalizeReading(raw.near);
    for (const key of ["value", "distance", "reading", "cm", "meters"]) {
      if (raw[key] !== undefined) return normalizeReading(raw[key]);
    }
  }
  return null;
}

function handleSensorEvent(event) {
  if (event.seq !== undefined) {
    if (seenEvents.has(event.seq)) return;
    seenEvents.add(event.seq);
    if (seenEvents.size > 500) seenEvents.delete(seenEvents.values().next().value);
  }
  const match = findProximity(event.payload);
  if (!match.found) return;
  const reading = normalizeReading(match.value);
  if (!reading) return;
  const now = Date.now();
  ui.reading.textContent = reading.display;
  const near = reading.near;
  ui.zone.classList.toggle("detecting", near);
  ui.pill.classList.toggle("detecting", near);
  $("zone-caption").textContent = near ? "NEAR FIELD" : "CLEAR";
  ui.status.textContent = near ? "Near field active" : "Clear";
  if (near && isNear !== true) {
    nearSince = now;
    if (hasBaseline && now - lastCountAt >= Number($("cooldown").value)) {
      setCount(total + 1);
      lastCountAt = now;
      $("last-detected").textContent = `Last object · ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
      addActivity("Proximity trigger", `#${String(total).padStart(2, "0")} · ${reading.numeric === null ? reading.display : `${reading.numeric.toFixed(2)} cm`}`);
    } else if (hasBaseline) {
      addActivity("Near reading ignored", "within spacing window");
    } else {
      addActivity("Sensor baseline", "waiting for a clear zone");
    }
  }
  if (!hasBaseline && !near) {
    addActivity("Sensor baseline", `clear · ${reading.numeric === null ? reading.display : `${reading.numeric.toFixed(2)} cm`}`);
  }
  if (!near && isNear === true) {
    const duration = now - nearSince;
    if (duration > 100) addActivity("Zone clear", `held ${(duration / 1000).toFixed(1)} sec`);
  }
  hasBaseline = true;
  isNear = near;
}

async function request(path, body) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Request failed.");
  return result;
}

async function refreshState() {
  try {
    const state = await request("/api/state");
    connectionState(state.connected, state.status);
    if (state.connected && !state.lastEventAt && ui.feed.querySelector(".empty-state")) {
      ui.feed.innerHTML = '<div class="empty-state"><span class="empty-icon">◌</span><span>Phone connected · waiting for sensor data</span><small>Enable Proximity streaming in Nikki Streams</small></div>';
    }
    if (state.error) {
      ui.error.textContent = state.error;
      ui.error.classList.remove("hidden");
    }
  } catch { /* the server can be starting or restarting */ }
}

const sensorEvents = new EventSource("/api/events");
sensorEvents.addEventListener("sensor", (message) => {
  try {
    const event = JSON.parse(message.data);
    if (event.kind === "data") handleSensorEvent(event);
    if (event.kind === "statusChange") refreshState();
  } catch { /* ignore malformed sensor messages */ }
});

$("connection-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  ui.error.classList.add("hidden");
  ui.connect.disabled = true;
  ui.connect.textContent = "Connecting…";
  connectionState(false, "Connecting…");
  try {
    await request("/api/connect", { sessionId: ui.session.value, phoneAddress: ui.address.value });
    toast("Updating your Nikki Streams connection…");
  } catch (error) {
    ui.error.textContent = error.message;
    ui.error.classList.remove("hidden");
    connectionState(false, "Not connected");
  }
  await refreshState();
});

$("disconnect-button").addEventListener("click", async () => {
  try { await request("/api/disconnect", {}); toast("Phone disconnected"); }
  catch (error) { toast(error.message); }
});

$("reset-button").addEventListener("click", () => {
  setCount(0);
  lastCountAt = 0;
  $("last-detected").textContent = "Waiting for first object";
  ui.feed.innerHTML = '<div class="empty-state"><span class="empty-icon">◌</span><span>Count reset</span><small>Ready for the next object</small></div>';
  toast("Counter reset to zero");
});

$("threshold").addEventListener("input", (event) => {
  $("threshold-value").textContent = Number(event.target.value).toFixed(1);
});
$("cooldown").addEventListener("input", (event) => {
  $("cooldown-value").textContent = event.target.value;
});

refreshState();
setInterval(refreshState, 1000);
