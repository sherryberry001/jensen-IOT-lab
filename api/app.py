from flask import Flask, jsonify, request, render_template
import os
import socket

import psycopg2

from db import (
    ONLINE_THRESHOLD_SECONDS,
    device_exists,
    get_devices,
    get_devices_with_status,
    get_latest_measurement,
    get_measurements,
    get_measurements_for_device,
    get_statistics,
    insert_measurement,
)
from validation import validate_measurement
from cache import cache_available, get_latest_from_cache, set_latest_in_cache

app = Flask(__name__)

APP_VERSION = os.getenv("APP_VERSION", "v1")
POD_NAME = socket.gethostname()


@app.get("/")
def dashboard():
    return render_template("index.html", version=APP_VERSION, pod=POD_NAME)


@app.get("/health")
def health():
    """Enkel hälsokontroll som medvetet inte rör PostgreSQL eller Redis.

    Beroendenas status rapporteras i stället av /health/dependencies, så att
    den här endpointen kan svara även när databasen är nere.
    """
    return jsonify({
        "status": "ok",
        "version": APP_VERSION,
        "pod": POD_NAME,
    }), 200


@app.get("/health/dependencies")
def health_dependencies():
    """Visar om PostgreSQL och Redis svarar."""
    try:
        get_devices()
        database_ok = True
    except psycopg2.Error:
        database_ok = False

    redis_ok = cache_available()

    payload = {
        "database": "ok" if database_ok else "unavailable",
        "cache": "ok" if redis_ok else "unavailable",
        "pod": POD_NAME,
    }
    # Redis är inte kritiskt: API:t fungerar utan cache. PostgreSQL är kritiskt.
    return jsonify(payload), 200 if database_ok else 503


@app.get("/devices")
def devices():
    return jsonify(get_devices()), 200


@app.get("/devices/status")
def devices_status():
    """Fördjupning: online/offline per sensor.

    En sensor räknas som online om dess senaste mätning kom in inom
    tröskelvärdet. Statusen härleds ur mätdatan i stället för att sensorerna
    skickar en egen heartbeat, vilket gör att den fungerar även för sensorer
    som inte kan rapportera att de mår dåligt.
    """
    return jsonify({
        "thresholdSeconds": ONLINE_THRESHOLD_SECONDS,
        "devices": get_devices_with_status(),
    }), 200


@app.get("/measurements")
def measurements():
    return jsonify(get_measurements()), 200


@app.get("/devices/<device_id>/latest")
def latest(device_id):
    """Senaste mätningen för en sensor, via cache-aside.

    1. Läs från Redis.
    2. Vid miss: läs från PostgreSQL.
    3. Skriv tillbaka till Redis så att nästa anrop träffar cachen.
    """
    cached = get_latest_from_cache(device_id)
    if cached is not None:
        return jsonify({"source": "cache", "measurement": cached}), 200

    measurement = get_latest_measurement(device_id)

    if measurement is None:
        if not device_exists(device_id):
            return jsonify({
                "error": "unknown device",
                "deviceId": device_id,
            }), 404
        return jsonify({
            "error": "no measurement for device",
            "deviceId": device_id,
        }), 404

    set_latest_in_cache(device_id, measurement)
    return jsonify({"source": "database", "measurement": measurement}), 200


@app.get("/devices/<device_id>/measurements")
def device_history(device_id):
    """Historik för en sensor.

    Skillnaden mellan tomt och okänt är viktig: en känd sensor utan mätningar
    är ett giltigt tillstånd och ger 200 med en tom lista, medan ett okänt
    sensor-id är ett klientfel och ger 404.
    """
    if not device_exists(device_id):
        return jsonify({
            "error": "unknown device",
            "deviceId": device_id,
        }), 404

    return jsonify(get_measurements_for_device(device_id)), 200


@app.post("/measurements")
def create_measurement():
    data = request.get_json(silent=True) or {}
    errors = validate_measurement(data)

    if errors:
        print(f"INVALID measurement from {data.get('deviceId', 'unknown')}: {errors}")
        return jsonify({"errors": errors}), 400

    device_id = data["deviceId"]

    # Okänd sensor är ett klientfel, inte ett serverfel. Utan den här kontrollen
    # hade främmande nyckel-villkoret i databasen gett ett 500-svar i stället.
    if not device_exists(device_id):
        print(f"UNKNOWN device rejected: {device_id}")
        return jsonify({
            "errors": [f"unknown deviceId: {device_id}"],
        }), 400

    measurement = insert_measurement(data)

    # Skrivningen håller cachen aktuell, så att en läsare direkt efter en POST
    # inte får ett gammalt värde serverat ur Redis.
    set_latest_in_cache(device_id, measurement)

    print(f"STORED measurement {measurement['id']} for {device_id}")
    response = jsonify({"status": "created", "measurement": measurement})
    response.headers["Location"] = f"/devices/{device_id}/latest"
    return response, 201


@app.get("/statistics")
def statistics():
    """Fördjupning: aggregerad statistik över alla sensorer."""
    return jsonify(get_statistics()), 200


@app.errorhandler(404)
def not_found(_error):
    return jsonify({"error": "not found", "path": request.path}), 404


@app.errorhandler(405)
def method_not_allowed(_error):
    return jsonify({"error": "method not allowed", "method": request.method}), 405


@app.errorhandler(psycopg2.Error)
def database_error(error):
    """Databasfel ska ge ett JSON-svar, inte Flasks HTML-sida."""
    print(f"DATABASE error on {request.path}: {error}")
    return jsonify({"error": "database unavailable"}), 503


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
