"""Conveyor Belt Object Counter powered by Nikki Streams proximity data."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
PHONE_ADDRESS = os.getenv("NIKKI_PHONE_ADDRESS", "")
HTTP_HOST = os.getenv("COUNTER_HOST", "127.0.0.1")
HTTP_PORT = int(os.getenv("COUNTER_PORT", "8000"))

state_lock = threading.RLock()
state = {
    "connected": False,
    "status": "Not connected",
    "phoneAddress": PHONE_ADDRESS,
    "latest": None,
    "lastEventAt": None,
    "error": None,
}
events: deque[dict] = deque(maxlen=100)
event_sequence = 0
events_changed = threading.Condition(state_lock)

# Each connection runs the official SDK in a fresh worker process. The SDK
# intentionally accepts one session ID per process, so this lets the user
# replace the address or session without restarting the dashboard.
worker_lock = threading.RLock()
worker_process: subprocess.Popen | None = None
worker_generation = 0


def publish(kind: str, payload: object) -> None:
    """Store a JSON-safe SDK event and wake any browser SSE clients."""
    global event_sequence
    try:
        safe_payload = json.loads(json.dumps(payload, default=lambda value: getattr(value, "__dict__", str(value))))
    except (TypeError, ValueError):
        safe_payload = str(payload)
    with events_changed:
        event_sequence += 1
        item = {"seq": event_sequence, "kind": kind, "payload": safe_payload, "at": time.time()}
        events.append(item)
        if kind == "statusChange":
            connected = safe_payload == "connected"
            state.update(connected=connected, status="Connected" if connected else "Disconnected")
            if connected:
                state["error"] = None
        elif kind == "data":
            state["latest"] = safe_payload
            state["lastEventAt"] = item["at"]
        elif kind == "error":
            state["connected"] = False
            state["status"] = "Connection failed"
            state["error"] = str(safe_payload)
        events_changed.notify_all()


def _worker_reader(process: subprocess.Popen, generation: int) -> None:
    """Forward one SDK worker's JSON-line events to the dashboard."""
    global worker_process
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            message = {"kind": "error", "payload": line}
        with worker_lock:
            is_current = generation == worker_generation and process is worker_process
        if is_current:
            publish(str(message.get("kind", "data")), message.get("payload"))

    return_code = process.wait()
    with worker_lock:
        is_current = generation == worker_generation and process is worker_process
        if is_current:
            # The SDK normally sends its own disconnected event. This also
            # covers a worker exit caused by a network failure or exception.
            worker_process = None
    if is_current:
        with events_changed:
            state["connected"] = False
            if return_code:
                state["status"] = "Connection failed"
                if not state["error"]:
                    state["error"] = f"Nikki Streams worker exited with code {return_code}."
            else:
                state["status"] = "Disconnected"
            events_changed.notify_all()


def _stop_worker_locked(status: str) -> None:
    """Stop the current worker. Caller must hold worker_lock."""
    global worker_process, worker_generation
    worker_generation += 1
    process = worker_process
    worker_process = None
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    with events_changed:
        state.update(connected=False, status=status)
        events_changed.notify_all()


def start_connection(session_id: str, address: str) -> None:
    """Replace the active phone connection with the supplied settings."""
    global worker_process
    with worker_lock:
        _stop_worker_locked("Connecting…")
        generation = worker_generation
        with events_changed:
            events.clear()
            state.update(
                connected=False,
                status="Connecting…",
                phoneAddress=address,
                latest=None,
                lastEventAt=None,
                error=None,
            )
            events_changed.notify_all()

        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--device-worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        worker_process = process
        assert process.stdin is not None
        process.stdin.write(json.dumps({"sessionId": session_id, "address": address}) + "\n")
        process.stdin.close()
        threading.Thread(
            target=_worker_reader,
            args=(process, generation),
            daemon=True,
            name="nikki-streams-reader",
        ).start()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _json(self, status: int, body: object) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/state":
            with state_lock:
                return self._json(200, {**state, "recent": list(events)[-20:]})
        if path == "/api/events":
            return self._sse()
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "Invalid JSON."})

        if path == "/api/connect":
            session_id = str(body.get("sessionId", "")).strip()
            address = str(body.get("phoneAddress", PHONE_ADDRESS)).strip()
            if not session_id:
                return self._json(400, {"error": "Enter the Streams session ID shown by the Nikki Streams app."})
            if address.startswith("ws://"):
                address = address[5:]
            if address.startswith("wss://"):
                address = address[6:]
            if not address or any(char in address for char in "?/\\"):
                return self._json(400, {"error": "Enter the phone socket host and port, such as 192.168.1.100:3000."})
            try:
                start_connection(session_id, address)
            except OSError as exc:
                with events_changed:
                    state.update(connected=False, status="Connection failed", error=str(exc))
                    events_changed.notify_all()
                return self._json(500, {"error": "Could not start the Nikki connection worker."})
            return self._json(202, {"status": "Connecting"})

        if path == "/api/disconnect":
            with worker_lock:
                _stop_worker_locked("Disconnected")
            publish("statusChange", "disconnected")
            return self._json(200, {"status": "Disconnected"})

        if path == "/api/reset":
            return self._json(200, {"status": "Reset"})
        return self._json(404, {"error": "Not found."})

    def _sse(self):
        cursor_header = self.headers.get("Last-Event-ID", "0")
        try:
            cursor = int(cursor_header)
        except ValueError:
            cursor = 0
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                with events_changed:
                    if not any(item["seq"] > cursor for item in events):
                        events_changed.wait(timeout=15)
                    batch_to_send = [item for item in events if item["seq"] > cursor]
                if not batch_to_send:
                    self.wfile.write(b": keep-alive\n\n")
                for item in batch_to_send:
                    self.wfile.write((f"id: {item['seq']}\nevent: sensor\ndata: " + json.dumps(item) + "\n\n").encode("utf-8"))
                    cursor = item["seq"]
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


def _worker_emit(event) -> None:
    payload = getattr(event, "data", event)
    message = {"kind": getattr(event, "type", "data"), "payload": payload}
    error = getattr(event, "error", None)
    if error:
        print(json.dumps({"kind": "error", "payload": str(error)}), flush=True)
    print(json.dumps(message, default=str), flush=True)


async def _run_device_worker(config: dict) -> None:
    from nikki_streams import SDK

    SDK.initialize(config["sessionId"])
    phone = SDK.create_device(config["address"], _worker_emit)
    await phone.connect()
    while phone.is_connected:
        await asyncio.sleep(0.25)
    await phone.disconnect()


def run_device_worker() -> None:
    try:
        config = json.loads(sys.stdin.readline())
        asyncio.run(_run_device_worker(config))
    except Exception as exc:
        print(json.dumps({"kind": "error", "payload": str(exc)}), flush=True)
        raise SystemExit(1)


def main() -> None:
    server = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), Handler)
    print(f"Conveyor Counter ready at http://{HTTP_HOST}:{HTTP_PORT}")
    print(f"Default Nikki Streams socket: {PHONE_ADDRESS}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping conveyor counter…")
    finally:
        with worker_lock:
            _stop_worker_locked("Disconnected")
        server.server_close()


if __name__ == "__main__":
    if "--device-worker" in sys.argv:
        run_device_worker()
    else:
        main()
