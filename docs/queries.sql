-- =============================================================================
-- Obligatoriska SQL-frågor - milstolpe 1
-- =============================================================================
--
-- Körs mot databasen jensen_iot. Öppna psql med:
--
--     docker compose exec db psql -U student -d jensen_iot
--
-- Tabellerna: devices (en rad per sensor) och measurements (en rad per mätning,
-- med främmande nyckel mot devices.device_id).
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. Totalt antal mätningar
-- -----------------------------------------------------------------------------
-- COUNT(*) räknar alla rader i tabellen. Eftersom API:t avvisar ogiltig data
-- innan den sparas motsvarar siffran antalet godkända mätningar, inte antalet
-- inkomna anrop. Simulatorns felaktiga rader från sensor-003 räknas alltså inte.

SELECT COUNT(*) AS total_measurements
FROM measurements;


-- -----------------------------------------------------------------------------
-- 2. Medeltemperatur
-- -----------------------------------------------------------------------------
-- AVG räknar bara på rader där temperature inte är NULL. temperature är NOT NULL
-- i schemat, så alla rader ingår. ROUND gör resultatet läsbart; utan den
-- returneras hela precisionen från NUMERIC(5,2)-kolumnen.

SELECT ROUND(AVG(temperature), 2) AS avg_temperature
FROM measurements;


-- -----------------------------------------------------------------------------
-- 3. Mätningar från de senaste 24 timmarna
-- -----------------------------------------------------------------------------
-- NOW() - INTERVAL '24 hours' räknas ut av databasen vid varje körning, så
-- fönstret följer med i tiden i stället för att vara ett fast datum.
-- Jämförelsen sker mot created_at, som sätts automatiskt av databasen när
-- raden skapas.

SELECT id, device_id, temperature, humidity, battery, created_at
FROM measurements
WHERE created_at >= NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;


-- Samma tidsfönster som en ren räkning, vilket är den form API:t använder
-- i fältet measurements_last_24h i /statistics.

SELECT COUNT(*) AS measurements_last_24h
FROM measurements
WHERE created_at >= NOW() - INTERVAL '24 hours';


-- =============================================================================
-- Fördjupning: analyser som ligger bakom /statistics
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 4. Sensorn med högst medeltemperatur
-- -----------------------------------------------------------------------------
-- GROUP BY delar upp mätningarna per sensor innan AVG räknas ut, så att man får
-- ett medelvärde per sensor i stället för ett för hela tabellen. Sorteringen
-- lägger den varmaste först och LIMIT 1 plockar ut den.
--
-- JOIN mot devices tar med plats och typ, vilket gör svaret användbart utan att
-- behöva slå upp sensorn separat.

SELECT
    d.device_id,
    d.location,
    ROUND(AVG(m.temperature), 2) AS avg_temperature,
    COUNT(*)                     AS measurement_count
FROM measurements m
JOIN devices d ON d.device_id = m.device_id
GROUP BY d.device_id, d.location
ORDER BY avg_temperature DESC
LIMIT 1;


-- Hela rankningen, som är den form /statistics returnerar i fältet perDevice.
-- Att titta på listan i stället för bara vinnaren gör det synligt om två
-- sensorer ligger nära varandra.

SELECT
    d.device_id,
    d.location,
    ROUND(AVG(m.temperature), 2) AS avg_temperature,
    MIN(m.temperature)           AS min_temperature,
    MAX(m.temperature)           AS max_temperature
FROM measurements m
JOIN devices d ON d.device_id = m.device_id
GROUP BY d.device_id, d.location
ORDER BY avg_temperature DESC;


-- -----------------------------------------------------------------------------
-- 5. Mest aktiv sensor
-- -----------------------------------------------------------------------------
-- Samma mönster, men aggregatet är COUNT i stället för AVG. "Mest aktiv"
-- betyder här flest godkända mätningar. Sensor-003 skickar med flit trasig data
-- ibland, och eftersom de raderna aldrig sparas hamnar den normalt sist.
-- Det är just den skillnaden mellan skickat och sparat som gör måttet
-- intressant att titta på.

SELECT
    d.device_id,
    d.location,
    COUNT(*)            AS measurement_count,
    MAX(m.created_at)   AS last_measurement_at
FROM measurements m
JOIN devices d ON d.device_id = m.device_id
GROUP BY d.device_id, d.location
ORDER BY measurement_count DESC
LIMIT 1;


-- -----------------------------------------------------------------------------
-- 6. Online/offline-status per sensor
-- -----------------------------------------------------------------------------
-- LEFT JOIN i stället för JOIN, så att en sensor som ännu inte skickat något
-- också kommer med i resultatet, men då med last_seen som NULL. CASE-uttrycket
-- ger offline för både NULL och för gamla värden, eftersom NULL >= tidpunkt
-- aldrig är sant.
--
-- Detta är frågan bakom endpointen GET /devices/status.

SELECT
    d.device_id,
    d.location,
    s.last_seen,
    COALESCE(s.measurement_count, 0) AS measurement_count,
    CASE
        WHEN s.last_seen >= NOW() - INTERVAL '30 seconds' THEN 'online'
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
