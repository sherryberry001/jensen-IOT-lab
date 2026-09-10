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
