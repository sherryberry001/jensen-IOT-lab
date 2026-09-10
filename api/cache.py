"""Redis-cache för varje sensors senaste mätning.

Cachen är medvetet byggd som "cache-aside": API:t frågar Redis först, går till
PostgreSQL vid en miss och skriver tillbaka svaret till Redis. PostgreSQL är
alltid sanningen. Därför fångas alla Redis-fel här inne och översätts till en
cache miss i stället för att slå igenom som ett fel mot klienten. Ett nedsläckt
Redis gör lösningen långsammare, inte trasig.
"""

import json
import os
import redis

# Hur länge en cachad senaste-mätning får leva. Utan TTL skulle värdet från en
# sensor som slutat skicka ligga kvar i cachen på obestämd tid.
LATEST_TTL_SECONDS = int(os.getenv("LATEST_TTL_SECONDS", "300"))

client = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def latest_key(device_id):
    """Nyckelformat: latest:sensor-001.

    Prefixet gör att nycklarna går att lista med KEYS "latest:*" och att andra
    typer av cachevärden kan läggas till senare utan att krocka.
    """
    return f"latest:{device_id}"


def get_latest_from_cache(device_id):
    """Läser senaste mätningen ur Redis. None betyder cache miss."""
    try:
        value = client.get(latest_key(device_id))
    except redis.RedisError as exc:
        print(f"CACHE unavailable on read for {device_id}: {exc}")
        return None

    if value is None:
        return None

    try:
        return json.loads(value)
    except (ValueError, TypeError) as exc:
        # Skadat värde ska inte kunna ta ner API:t. Behandla som en miss.
        print(f"CACHE corrupt value for {device_id}: {exc}")
        return None


def set_latest_in_cache(device_id, measurement):
    """Skriver senaste mätningen till Redis med TTL. Fel loggas men kastas inte."""
    if measurement is None:
        return
    try:
        client.setex(
            latest_key(device_id),
            LATEST_TTL_SECONDS,
            json.dumps(measurement),
        )
    except redis.RedisError as exc:
        print(f"CACHE unavailable on write for {device_id}: {exc}")


def cache_available():
    """Används av /health/dependencies för att visa om Redis svarar."""
    try:
        return bool(client.ping())
    except redis.RedisError:
        return False
