from validation import validate_measurement


def test_valid_measurement():
    data = {
        "deviceId": "sensor-001",
        "temperature": 21.5,
        "humidity": 45.0,
        "battery": 90,
    }
    assert validate_measurement(data) == []


def test_missing_temperature():
    data = {
        "deviceId": "sensor-001",
        "humidity": 45.0,
        "battery": 90,
    }
    assert "temperature is required" in validate_measurement(data)


def test_invalid_temperature_type():
    data = {
        "deviceId": "sensor-003",
        "temperature": "ERROR",
    }
    assert "temperature must be a number" in validate_measurement(data)


# --- Obligatoriska tillägg i milstolpe 1 -------------------------------------


def test_missing_device_id():
    """Ett mätvärde utan avsändare går inte att koppla till en sensor."""
    data = {
        "temperature": 21.5,
        "humidity": 45.0,
        "battery": 90,
    }
    assert "deviceId is required" in validate_measurement(data)


def test_invalid_humidity_type():
    data = {
        "deviceId": "sensor-001",
        "temperature": 21.5,
        "humidity": "wet",
    }
    assert "humidity must be a number" in validate_measurement(data)


def test_invalid_battery_type():
    """battery lagras som INTEGER, så ett decimaltal ska avvisas."""
    data = {
        "deviceId": "sensor-001",
        "temperature": 21.5,
        "battery": 90.5,
    }
    assert "battery must be an integer" in validate_measurement(data)
