import os
from contextlib import contextmanager
from decimal import Decimal
import psycopg2
import psycopg2.extras


# Kolumnlistan används av flera frågor. Att hålla den på ett ställe gör att
# API:t alltid returnerar samma fält oavsett vilken endpoint som svarar.
MEASUREMENT_COLUMNS = "id, device_id, temperature, humidity, battery, created_at"

# En sensor räknas som online om den skickat in ett mätvärde inom så här många
# sekunder. Simulatorn skickar var femte sekund, så 30 sekunder ger marginal
# för några missade intervall innan sensorn flaggas som offline.
ONLINE_THRESHOLD_SECONDS = int(os.getenv("ONLINE_THRESHOLD_SECONDS", "30"))


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "db"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "jensen_iot"),
        user=os.getenv("DB_USER", "student"),
        password=os.getenv("DB_PASSWORD", "student"),
    )


@contextmanager
def _cursor(dict_rows=True):
    """Öppnar anslutning och cursor, commitar vid lyckad körning och stänger alltid.

    psycopg2:s connection commitar när `with conn`-blocket lämnas utan fel och
    rullar tillbaka vid undantag, men den stänger inte anslutningen. Utan det
    yttre try/finally skulle varje anrop lämna en öppen anslutning kvar tills
    garbage collectorn hinner ikapp, och simulatorn som postar var femte sekund
    skulle till slut slå i PostgreSQL:s max_connections.
    """
    conn = get_connection()
    try:
        with conn:
            factory = psycopg2.extras.RealDictCursor if dict_rows else None
            with conn.cursor(cursor_factory=factory) as cur:
                yield cur
    finally:
        conn.close()


def _json_ready(row):
    if row is None:
        return None
    result = dict(row)
    for key in ("temperature", "humidity"):
        if isinstance(result.get(key), Decimal):
            result[key] = float(result[key])
    if result.get("created_at") is not None:
        result["created_at"] = result["created_at"].isoformat()
    return result


def _query(sql, params=None, one=False):
    """Kör en sats och returnerar rader som går att serialisera till JSON.

    Fungerar även för INSERT ... RETURNING eftersom `_cursor` commitar.
    """
    with _cursor() as cur:
        cur.execute(sql, params or ())
        if one:
            return _json_ready(cur.fetchone())
        return [_json_ready(row) for row in cur.fetchall()]


def get_devices():
    query = """
        SELECT id, device_id, location, device_type
        FROM devices
        ORDER BY device_id;
    """
    with _cursor() as cur:
        cur.execute(query)
        return [dict(row) for row in cur.fetchall()]


def get_measurements():
    query = f"""
        SELECT {MEASUREMENT_COLUMNS}
        FROM measurements
        ORDER BY created_at DESC, id DESC
        LIMIT 100;
    """
    return _query(query)


def device_exists(device_id):
    """True om device_id finns i tabellen devices."""
    query = "SELECT 1 FROM devices WHERE device_id = %s;"
    with _cursor(dict_rows=False) as cur:
        cur.execute(query, (device_id,))
        return cur.fetchone() is not None


def get_latest_measurement(device_id):
    """Senaste mätvärdet för en sensor, eller None om sensorn saknar mätningar.

    Sorteringen har id som sekundär nyckel eftersom created_at sätts av NOW(),
    som är transaktionens starttid. Två rader kan därför få samma tidsstämpel.
    """
    query = f"""
        SELECT {MEASUREMENT_COLUMNS}
        FROM measurements
        WHERE device_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT 1;
    """
    return _query(query, (device_id,), one=True)


def get_measurements_for_device(device_id):
    """Historik för en sensor. Tom lista betyder känd sensor utan mätningar."""
    query = f"""
        SELECT {MEASUREMENT_COLUMNS}
        FROM measurements
        WHERE device_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT 100;
    """
    return _query(query, (device_id,))


def insert_measurement(data):
    """Sparar ett validerat mätvärde och returnerar den skapade raden.

    JSON använder deviceId medan databaskolumnen heter device_id. Översättningen
    görs här, på ett ställe, så att resten av koden slipper hålla reda på det.
    Värdena skickas som parametrar och inte som stränginterpolation, vilket är
    det som skyddar mot SQL-injektion.
    """
    query = f"""
        INSERT INTO measurements (device_id, temperature, humidity, battery)
        VALUES (%s, %s, %s, %s)
        RETURNING {MEASUREMENT_COLUMNS};
    """
    params = (
        data["deviceId"],
        data["temperature"],
        data.get("humidity"),
        data.get("battery"),
    )
    return _query(query, params, one=True)


# --- Fördjupning: statistik och sensorstatus ---------------------------------


def _clean(row):
    """Gör en aggregatrad JSON-vänlig: Decimal -> float, tidsstämpel -> ISO 8601."""
    out = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            out[key] = float(value)
        elif key.endswith("_at") and value is not None:
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


def get_statistics():
    """Aggregerad statistik för /statistics.

    Bygger på samma aggregat som de obligatoriska SQL-uppgifterna (COUNT, AVG
    och ett 24-timmarsfilter) och lägger till min/max samt en nedbrytning per
    sensor, som i sin tur ger svaret på fördjupningsfrågorna om varmaste och
    mest aktiva sensor.
    """
    totals_query = """
        SELECT
            (SELECT COUNT(*) FROM devices)  AS device_count,
            COUNT(*)                        AS measurement_count,
            ROUND(AVG(temperature), 2)      AS avg_temperature,
            MIN(temperature)                AS min_temperature,
            MAX(temperature)                AS max_temperature,
            ROUND(AVG(humidity), 2)         AS avg_humidity,
            ROUND(AVG(battery), 1)          AS avg_battery,
            MAX(created_at)                 AS last_measurement_at,
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            )                               AS measurements_last_24h
        FROM measurements;
    """

    per_device_query = """
        SELECT
            device_id,
            COUNT(*)                    AS measurement_count,
            ROUND(AVG(temperature), 2)  AS avg_temperature,
            MIN(temperature)            AS min_temperature,
            MAX(temperature)            AS max_temperature,
            MAX(created_at)             AS last_measurement_at
        FROM measurements
        GROUP BY device_id
        ORDER BY device_id;
    """

    with _cursor() as cur:
        cur.execute(totals_query)
        totals = _clean(cur.fetchone())
        cur.execute(per_device_query)
        per_device = [_clean(row) for row in cur.fetchall()]

    warmest = max(
        (row for row in per_device if row["avg_temperature"] is not None),
        key=lambda row: row["avg_temperature"],
        default=None,
    )
    most_active = max(
        per_device,
        key=lambda row: row["measurement_count"],
        default=None,
    )

    return {
        "totals": totals,
        "perDevice": per_device,
        "warmestDevice": warmest,
        "mostActiveDevice": most_active,
    }


def get_devices_with_status(threshold_seconds=ONLINE_THRESHOLD_SECONDS):
    """Sensorer med online/offline-status baserat på senaste inkomna mätning.

    LEFT JOIN gör att en sensor som ännu inte skickat något också kommer med,
    men då som offline med last_seen = null.
    """
    query = """
        SELECT
            d.id,
            d.device_id,
            d.location,
            d.device_type,
            s.last_seen,
            COALESCE(s.measurement_count, 0) AS measurement_count,
            CASE
                WHEN s.last_seen >= NOW() - make_interval(secs => %s) THEN 'online'
                ELSE 'offline'
            END AS status
        FROM devices d
        LEFT JOIN (
            SELECT device_id,
                   MAX(created_at) AS last_seen,
                   COUNT(*)        AS measurement_count
            FROM measurements
            GROUP BY device_id
        ) s ON s.device_id = d.device_id
        ORDER BY d.device_id;
    """
    with _cursor() as cur:
        cur.execute(query, (threshold_seconds,))
        rows = [dict(row) for row in cur.fetchall()]

    for row in rows:
        if row.get("last_seen") is not None:
            row["last_seen"] = row["last_seen"].isoformat()
    return rows
