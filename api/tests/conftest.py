"""Gemensamma fixtures för integrationstesterna.

Integrationstesterna kräver en riktig PostgreSQL och en riktig Redis. De körs
därför i API-containern eller i CI, där båda tjänsterna finns. Kör man pytest
på en maskin utan dem hoppas testerna över i stället för att fallera, så att
enhetstesterna för valideringen alltid går att köra fristående.
"""

from contextlib import contextmanager

import psycopg2
import pytest
import redis

import cache
import db
from app import app as flask_app

# Egen sensor för testerna, så att de aldrig rör simulatorns data.
TEST_DEVICE_ID = "sensor-int-test"


def _database_available():
    try:
        connection = db.get_connection()
        connection.close()
        return True
    except psycopg2.Error:
        return False


def _redis_available():
    try:
        return bool(cache.client.ping())
    except redis.RedisError:
        return False


DATABASE_AVAILABLE = _database_available()
REDIS_AVAILABLE = _redis_available()

requires_database = pytest.mark.skipif(
    not DATABASE_AVAILABLE,
    reason="PostgreSQL svarar inte. Kör testerna med docker compose eller i CI.",
)

requires_redis = pytest.mark.skipif(
    not REDIS_AVAILABLE,
    reason="Redis svarar inte. Kör testerna med docker compose eller i CI.",
)


@contextmanager
def admin_cursor():
    """Direkt databasåtkomst för uppsättning och städning, utanför API:t."""
    connection = db.get_connection()
    try:
        with connection:
            with connection.cursor() as cur:
                yield cur
    finally:
        connection.close()


def forget_cached_latest(device_id):
    try:
        cache.client.delete(cache.latest_key(device_id))
    except redis.RedisError:
        pass


def _remove_test_device():
    with admin_cursor() as cur:
        # Måste tas bort i den här ordningen: measurements.device_id har en
        # främmande nyckel mot devices.device_id.
        cur.execute("DELETE FROM measurements WHERE device_id = %s;", (TEST_DEVICE_ID,))
        cur.execute("DELETE FROM devices WHERE device_id = %s;", (TEST_DEVICE_ID,))
    forget_cached_latest(TEST_DEVICE_ID)


@pytest.fixture
def client():
    flask_app.config.update(TESTING=True)
    return flask_app.test_client()


@pytest.fixture
def test_device():
    """Skapar en tom testsensor, lämnar över den och städar bort den efteråt."""
    _remove_test_device()
    with admin_cursor() as cur:
        cur.execute(
            "INSERT INTO devices (device_id, location, device_type) "
            "VALUES (%s, %s, %s);",
            (TEST_DEVICE_ID, "Test Lab", "environment"),
        )
    yield TEST_DEVICE_ID
    _remove_test_device()


@pytest.fixture
def measurement_payload(test_device):
    return {
        "deviceId": test_device,
        "temperature": 21.5,
        "humidity": 45.0,
        "battery": 90,
    }
