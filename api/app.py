from flask import Flask, jsonify, request, render_template
import os
import socket

import psycopg2

from db import (
    device_exists,
    get_devices,
    get_latest_measurement,
    get_measurements,
    get_measurements_for_device,
    insert_measurement,
)
from validation import validate_measurement
from cache import get_latest_from_cache, set_latest_in_cache

app = Flask(__name__)

APP_VERSION = os.getenv("APP_VERSION", "v1")
POD_NAME = socket.gethostname()


@app.get("/")
def dashboard():
    return render_template("index.html", version=APP_VERSION, pod=POD_NAME)


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "version": APP_VERSION,
        "pod": POD_NAME,
    }), 200


@app.get("/devices")
def devices():
    return jsonify(get_devices()), 200


@app.get("/measurements")
def measurements():
    return jsonify(get_measurements()), 200


@app.get("/devices/<device_id>/latest")
def latest(device_id):
    """Senaste mätningen för en sensor."""
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

    print(f"STORED measurement {measurement['id']} for {device_id}")
    response = jsonify({"status": "created", "measurement": measurement})
    response.headers["Location"] = f"/devices/{device_id}/latest"
    return response, 201


@app.get("/statistics")
def statistics():
    # ⭐ Utmaning:
    # Returnera antal devices, antal measurements, avg temp etc.
    return jsonify({"message": "Optional challenge"}), 501


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
