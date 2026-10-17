# Conveyor Belt Object Counter

A live near-field trigger counter that uses the Nikki Streams **Proximity** sensor on your phone. It increments on each clear-to-near transition, so a stationary obstruction is counted once until the sensor clears. It uses sensor readings only; there is no camera, AI, or image recognition.

## Start it

Requires Python 3.10 or newer and the Nikki Streams Android app on the same local network.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000), enter the active **Streams session ID** and the phone socket host and port shown by Nikki Streams, then connect. The address changes with the phone/network; the SDK wants a host and port, so the `ws://` prefix is optional.

The session ID stays in the open dashboard tab and the active Nikki SDK worker's memory; it is not written to project files or browser storage. To change the socket address or session ID, edit the fields and choose **Update connection**. The old phone link is replaced without restarting the dashboard.

## Use the counter

1. In Nikki Streams, create or open a session and enable **Proximity** sensor streaming.
2. Connect this app using the session ID shown in that session.
3. Secure the phone in a holder with its proximity sensor (usually near the top speaker/front of the phone) aimed at the path. Keep your hands away from the sensor. Observe readings, then adjust **Near threshold** to match the sensor's actual readings.
4. Adjust **Object spacing** to suppress extra triggers when objects are close together.

The activity feed shows proximity data and count changes. **Reset count** sets the displayed count back to zero.

## Detection behavior

The count increases once when a reading crosses from clear to near. Numeric readings (including Nikki's `Prox` field) use the configurable threshold; boolean or named near/far readings are also supported. A cooldown blocks fast repeated triggers. Android phone proximity sensors are designed for very short range (often only a few centimeters), and many report only near/far or a maximum-range value while clear. They cannot identify whether the nearby thing is a hand or a product. Keep the sensor mounted and unobstructed between passes. If items pass beyond the sensor's range or a hand can trigger it, this phone sensor is not suitable for that conveyor setup; use a dedicated longer-range proximity sensor connected through a supported Nikki Streams device instead.

## Configuration

Optional environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `NIKKI_PHONE_ADDRESS` | empty | Optional Nikki Streams phone socket address |
| `COUNTER_HOST` | `127.0.0.1` | Local web server bind address |
| `COUNTER_PORT` | `8000` | Local web server port |

Keep `COUNTER_HOST` on `127.0.0.1` for local browser access only.
