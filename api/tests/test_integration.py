"""Integrationstester mot ett riktigt PostgreSQL och Redis (frivillig fördjupning).

Enhetstesterna i test_validation.py testar en ren funktion. Testerna här går i
stället genom hela kedjan: HTTP-anrop via Flasks testklient, validering,
SQL-fråga mot databasen och läsning eller skrivning mot cachen. Det är den
kedjan som guidens manuella kontroller går igenom för hand, automatiserad så
att den körs vid varje push.
"""

from datetime import datetime, timezone

from conftest import forget_cached_latest, requires_database, requires_redis

import cache


def test_health_does_not_require_the_database(client):
    """/health används som readiness-probe i Kubernetes, där ingen databas finns."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


# --- POST /measurements ------------------------------------------------------


@requires_database
def test_post_valid_measurement_is_stored_and_returns_201(client, measurement_payload):
    response = client.post("/measurements", json=measurement_payload)

    assert response.status_code == 201
    stored = response.get_json()["measurement"]
    assert stored["device_id"] == measurement_payload["deviceId"]
    assert stored["temperature"] == measurement_payload["temperature"]
    # Databasen fyller i id och tidsstämpel.
    assert stored["id"] > 0
    assert stored["created_at"] is not None

    history = client.get(f"/devices/{measurement_payload['deviceId']}/measurements")
    assert history.status_code == 200
    assert len(history.get_json()) == 1


@requires_database
def test_post_invalid_measurement_returns_400_and_is_not_stored(client, test_device):
    response = client.post(
        "/measurements",
        json={"deviceId": test_device, "temperature": "ERROR"},
    )

    assert response.status_code == 400
    assert "temperature must be a number" in response.get_json()["errors"]

    history = client.get(f"/devices/{test_device}/measurements")
    assert history.get_json() == []


@requires_database
def test_post_unknown_device_returns_400(client):
    """Okänd sensor ska fångas av API:t, inte av databasens främmande nyckel."""
    response = client.post(
        "/measurements",
        json={"deviceId": "sensor-999", "temperature": 21.5},
    )

    assert response.status_code == 400
    assert "unknown deviceId: sensor-999" in response.get_json()["errors"]


@requires_database
def test_post_without_body_returns_400(client):
    response = client.post("/measurements")

    assert response.status_code == 400
    assert "deviceId is required" in response.get_json()["errors"]


# --- GET /devices och historik ----------------------------------------------


@requires_database
def test_devices_lists_the_seeded_sensors(client):
    response = client.get("/devices")

    assert response.status_code == 200
    device_ids = [device["device_id"] for device in response.get_json()]
    assert {"sensor-001", "sensor-002", "sensor-003"} <= set(device_ids)


@requires_database
def test_history_for_known_device_without_measurements_is_empty_list(client, test_device):
    """Känd sensor utan mätningar är ett giltigt tillstånd, inte ett fel."""
    response = client.get(f"/devices/{test_device}/measurements")

    assert response.status_code == 200
    assert response.get_json() == []


@requires_database
def test_history_for_unknown_device_returns_404(client):
    response = client.get("/devices/sensor-999/measurements")

    assert response.status_code == 404
    assert response.get_json()["error"] == "unknown device"


@requires_database
def test_history_is_sorted_newest_first(client, measurement_payload):
    for temperature in (20.0, 21.0, 22.0):
        payload = dict(measurement_payload, temperature=temperature)
        assert client.post("/measurements", json=payload).status_code == 201

    history = client.get(
        f"/devices/{measurement_payload['deviceId']}/measurements"
    ).get_json()

    assert [row["temperature"] for row in history] == [22.0, 21.0, 20.0]


# --- GET /devices/<id>/latest och cachen ------------------------------------


@requires_database
def test_latest_for_unknown_device_returns_404(client):
    response = client.get("/devices/sensor-999/latest")

    assert response.status_code == 404
    assert response.get_json()["error"] == "unknown device"


@requires_database
def test_latest_for_known_device_without_measurements_returns_404(client, test_device):
    """Skiljer sig från okänd sensor: sensorn finns, men har inte mätt något."""
    response = client.get(f"/devices/{test_device}/latest")

    assert response.status_code == 404
    assert response.get_json()["error"] == "no measurement for device"


@requires_database
@requires_redis
def test_post_populates_the_cache(client, measurement_payload):
    device_id = measurement_payload["deviceId"]

    client.post("/measurements", json=measurement_payload)

    assert cache.client.get(cache.latest_key(device_id)) is not None
    assert client.get(f"/devices/{device_id}/latest").get_json()["source"] == "cache"


@requires_database
@requires_redis
def test_cache_miss_falls_back_to_postgres_and_repopulates(client, measurement_payload):
    """Guidens FLUSHDB-kontroll, automatiserad.

    Ett tomt Redis får inte innebära att data försvinner. Första läsningen efter
    en tömning ska komma från PostgreSQL och samtidigt lägga tillbaka värdet i
    cachen, så att nästa läsning träffar cachen igen.
    """
    device_id = measurement_payload["deviceId"]
    client.post("/measurements", json=measurement_payload)

    forget_cached_latest(device_id)

    from_database = client.get(f"/devices/{device_id}/latest")
    assert from_database.status_code == 200
    assert from_database.get_json()["source"] == "database"

    from_cache = client.get(f"/devices/{device_id}/latest")
    assert from_cache.status_code == 200
    assert from_cache.get_json()["source"] == "cache"

    assert (
        from_cache.get_json()["measurement"]
        == from_database.get_json()["measurement"]
    )


@requires_database
@requires_redis
def test_latest_reflects_the_newest_measurement(client, measurement_payload):
    """En ny POST ska uppdatera cachen, annars serveras ett gammalt värde."""
    device_id = measurement_payload["deviceId"]

    client.post("/measurements", json=dict(measurement_payload, temperature=20.0))
    client.post("/measurements", json=dict(measurement_payload, temperature=24.0))

    latest = client.get(f"/devices/{device_id}/latest").get_json()
    assert latest["measurement"]["temperature"] == 24.0


# --- Fördjupningar: /statistics och /devices/status -------------------------


@requires_database
def test_statistics_returns_aggregates(client, measurement_payload):
    client.post("/measurements", json=dict(measurement_payload, temperature=20.0))
    client.post("/measurements", json=dict(measurement_payload, temperature=24.0))

    response = client.get("/statistics")
    assert response.status_code == 200

    body = response.get_json()
    assert body["totals"]["measurement_count"] >= 2
    assert body["totals"]["avg_temperature"] is not None
    assert body["totals"]["measurements_last_24h"] >= 2
    assert body["mostActiveDevice"] is not None
    assert body["warmestDevice"] is not None

    per_device = {row["device_id"]: row for row in body["perDevice"]}
    ours = per_device[measurement_payload["deviceId"]]
    assert ours["measurement_count"] == 2
    assert ours["avg_temperature"] == 22.0
    assert ours["min_temperature"] == 20.0
    assert ours["max_temperature"] == 24.0


@requires_database
def test_device_status_is_online_right_after_a_measurement(client, measurement_payload):
    device_id = measurement_payload["deviceId"]
    client.post("/measurements", json=measurement_payload)

    response = client.get("/devices/status")
    assert response.status_code == 200

    devices = {row["device_id"]: row for row in response.get_json()["devices"]}
    assert devices[device_id]["status"] == "online"
    assert devices[device_id]["measurement_count"] == 1


@requires_database
def test_timestamps_carry_an_explicit_timezone(client, measurement_payload):
    """Regressionstest för en tidszonsbugg.

    created_at är TIMESTAMP utan tidszon i databasen. Skickades värdet vidare
    naivt tolkade webbläsaren det som lokal tid, och dashboarden visade att en
    sensor senast hörts av för två timmar sedan trots att den var online.
    """
    response = client.post("/measurements", json=measurement_payload)
    created_at = response.get_json()["measurement"]["created_at"]

    assert created_at.endswith("+00:00"), created_at

    parsed = datetime.fromisoformat(created_at)
    assert parsed.tzinfo is not None
    # Tiden ska ligga nära nu, inte timmar bort.
    assert abs((datetime.now(timezone.utc) - parsed).total_seconds()) < 60


@requires_database
def test_age_is_calculated_by_the_server(client, measurement_payload):
    """Åldern räknas i databasen, så klientens klocka spelar ingen roll."""
    device_id = measurement_payload["deviceId"]
    client.post("/measurements", json=measurement_payload)

    devices = {
        row["device_id"]: row
        for row in client.get("/devices/status").get_json()["devices"]
    }

    assert devices[device_id]["seconds_since_last_seen"] < 10


@requires_database
def test_device_without_measurements_is_offline(client, test_device):
    response = client.get("/devices/status")

    devices = {row["device_id"]: row for row in response.get_json()["devices"]}
    assert devices[test_device]["status"] == "offline"
    assert devices[test_device]["last_seen"] is None


@requires_database
def test_dependency_health_reports_both_services(client):
    response = client.get("/health/dependencies")

    assert response.status_code == 200
    assert response.get_json()["database"] == "ok"


def test_unknown_route_returns_json_404(client):
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.get_json()["error"] == "not found"
