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


# --- Ytterligare kantfall ----------------------------------------------------


def test_boolean_is_not_accepted_as_number():
    """isinstance(True, int) är True i Python, så bool måste stängas ute explicit.

    Utan den kontrollen hade {"temperature": true} sparats som 1 grad.
    """
    errors = validate_measurement({"deviceId": "sensor-001", "temperature": True})
    assert "temperature must be a number" in errors

    errors = validate_measurement(
        {"deviceId": "sensor-001", "temperature": 21.5, "battery": True}
    )
    assert "battery must be an integer" in errors


def test_device_id_must_be_a_string():
    errors = validate_measurement({"deviceId": 1, "temperature": 21.5})
    assert "deviceId must be a string" in errors


def test_temperature_out_of_physical_range_is_rejected():
    errors = validate_measurement({"deviceId": "sensor-001", "temperature": 5000})
    assert any("temperature must be between" in error for error in errors)


def test_humidity_out_of_range_is_rejected():
    errors = validate_measurement(
        {"deviceId": "sensor-001", "temperature": 21.5, "humidity": 140}
    )
    assert any("humidity must be between" in error for error in errors)


def test_battery_out_of_range_is_rejected():
    errors = validate_measurement(
        {"deviceId": "sensor-001", "temperature": 21.5, "battery": 150}
    )
    assert any("battery must be between" in error for error in errors)


def test_optional_fields_may_be_omitted():
    """humidity och battery är valfria i databasschemat och ska få saknas."""
    assert validate_measurement({"deviceId": "sensor-002", "temperature": 19.0}) == []


def test_several_errors_are_reported_together():
    """Klienten ska få veta allt som är fel på en gång, inte ett fel i taget."""
    errors = validate_measurement({"humidity": "wet", "battery": 1.5})
    assert "deviceId is required" in errors
    assert "temperature is required" in errors
    assert "humidity must be a number" in errors
    assert "battery must be an integer" in errors
