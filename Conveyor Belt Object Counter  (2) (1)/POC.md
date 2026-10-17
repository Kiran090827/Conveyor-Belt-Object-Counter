# Technical POC: Conveyor Belt Proximity Counter

## Objective

Prototype a live counter driven by the Android phone's Proximity sensor via Nikki Streams. This implementation consumes sensor readings only; it does not use the camera, computer vision, AI, or image recognition.

## System architecture

```text
Android Proximity sensor
        │
        ▼
Nikki Streams app + WebSocket session
        │  nikki-streams SDK (async worker process)
        ▼
Python HTTP server ── stores events / exposes Server-Sent Events
        │  GET /api/events (text/event-stream)
        ▼
Browser dashboard ── parses readings, applies threshold and edge logic
        └── live trigger count + reading + activity feed
```

The Python server runs the Nikki SDK in a child process for each connection. That lets the dashboard replace the session ID or socket address without restarting the local HTTP server. The session ID is sent to the worker through standard input and is not saved to a project file.

## Software and data path

### Dependencies

- Python 3.10 or newer
- `nikki-streams==1.0.3` (declared in `requirements.txt`)
- Nikki Streams Android app and an active session with Proximity streaming enabled
- Browser with `EventSource` support

### SDK worker

The worker initializes the Nikki SDK with the session ID, creates the phone device using the configured socket address, then forwards SDK events as JSON lines to the parent server:

```python
async def _run_device_worker(config: dict) -> None:
    from nikki_streams import SDK

    SDK.initialize(config["sessionId"])
    phone = SDK.create_device(config["address"], _worker_emit)
    await phone.connect()
    while phone.is_connected:
        await asyncio.sleep(0.25)
    await phone.disconnect()
```

The callback extracts the SDK event payload and writes a JSON line to stdout. The parent process reads these lines, stores them in a bounded in-memory event queue, and wakes connected dashboard clients.

### Browser event transport

The browser subscribes to the local server with Server-Sent Events (SSE):

```javascript
const sensorEvents = new EventSource("/api/events");
sensorEvents.addEventListener("sensor", (message) => {
  const event = JSON.parse(message.data);
  if (event.kind === "data") handleSensorEvent(event);
  if (event.kind === "statusChange") refreshState();
});
```

SSE is used for server-to-browser updates. The dashboard sends connection settings to `POST /api/connect` as JSON. `GET /api/state` returns the current connection state, and `POST /api/disconnect` stops the active worker.

## Detection algorithm

Incoming payloads are searched for proximity fields (`proximity`, `prox`, `distance`, `near`) including common nested sensor/data objects. Numeric values are compared with the dashboard threshold. The default threshold is 4.9 cm; change it to match actual sensor output. Boolean and named `near`/`far` values are supported too.

The counter uses a state transition rather than counting every sensor event. It first waits for at least one clear reading to establish a baseline. It then increments once on a clear-to-near edge and waits for a near-to-clear edge before another pass can be counted. The object-spacing setting additionally rejects a transition that occurs too soon after the last count.

```javascript
if (near && isNear !== true) {
  if (hasBaseline && now - lastCountAt >= Number($("cooldown").value)) {
    setCount(total + 1);
    lastCountAt = now;
    addActivity("Proximity trigger", `#${String(total).padStart(2, "0")}`);
  }
}

if (!hasBaseline && !near) {
  // First clear reading establishes the baseline; it is not counted.
}

hasBaseline = true;
isNear = near;
```

`isNear` stores the previous sensor state; `hasBaseline` prevents an initial near reading (for example, a hand already covering the sensor at startup) from being treated as a pass. The counter lives in browser memory and resets when the page is reloaded; the Reset button clears the displayed count.

## Running the POC

Follow [README.md](README.md) for installation and startup. Enable Proximity streaming in Nikki Streams, then enter the current phone socket address and session ID in the local dashboard. Use the live reading display to tune the near threshold. Secure the phone so its proximity sensor faces the path and is clear between passes.

## Scope and limitations

This POC demonstrates the software path from phone sensor data to a live browser counter. It counts near-field sensor triggers, not semantically identified products. Phone proximity sensors are designed for very short distances (often only a few centimeters); many report only a near/far value or their maximum-range value while clear. The sensor cannot distinguish a person's hand from a conveyor item. A hand near the sensor will trigger the same reading as an item.

For a conveyor with a larger gap or a requirement to separate hands from products, use an appropriate longer-range industrial proximity sensor and a Nikki Streams-compatible source that publishes that sensor's data. The phone's built-in Proximity sensor cannot provide that capability in software.

## Repository files

- `main.py` — local HTTP/SSE server, connection API, Nikki SDK worker lifecycle.
- `web/index.html` — dashboard structure and settings.
- `web/app.js` — event parsing, thresholding, state transitions, UI updates.
- `web/styles.css` — dashboard presentation.
- `requirements.txt` — Python dependency pin.
- `README.md` — installation and user setup instructions.
- `.gitignore` — excludes local virtual environments and Python cache files.
