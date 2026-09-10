"""Validering av inkommande mätvärden.

Valideringen körs innan något skrivs till PostgreSQL. Den har två uppgifter:
stoppa data som inte går att lagra (fel datatyp, saknade fält) och stoppa data
som är tekniskt lagringsbar men fysiskt orimlig (temperatur på 5000 grader).
Felmeddelandena är formulerade så att avsändaren ska förstå vad som är fel.
"""

# Rimliga intervall för en miljösensor. Gränserna är generösa med flit: syftet
# är att fånga trasiga sensorer och felkopplade fält, inte att slå bort ovanliga
# men möjliga mätvärden.
TEMPERATURE_RANGE = (-50, 100)
HUMIDITY_RANGE = (0, 100)
BATTERY_RANGE = (0, 100)


def _is_number(value):
    """True för int och float, men inte för bool.

    isinstance(True, int) är True i Python eftersom bool ärver från int. Utan
    den här kontrollen skulle {"temperature": true} passera valideringen och
    sedan sparas som 1 i databasen.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def validate_measurement(data):
    """Returnerar en lista med fel. Tom lista betyder att mätvärdet är giltigt."""
    errors = []

    device_id = data.get("deviceId")
    if not device_id:
        errors.append("deviceId is required")
    elif not isinstance(device_id, str):
        errors.append("deviceId must be a string")

    if "temperature" not in data:
        errors.append("temperature is required")
    elif not _is_number(data["temperature"]):
        errors.append("temperature must be a number")
    elif not TEMPERATURE_RANGE[0] <= data["temperature"] <= TEMPERATURE_RANGE[1]:
        errors.append(
            f"temperature must be between {TEMPERATURE_RANGE[0]} "
            f"and {TEMPERATURE_RANGE[1]}"
        )

    if "humidity" in data and data["humidity"] is not None:
        if not _is_number(data["humidity"]):
            errors.append("humidity must be a number")
        elif not HUMIDITY_RANGE[0] <= data["humidity"] <= HUMIDITY_RANGE[1]:
            errors.append(
                f"humidity must be between {HUMIDITY_RANGE[0]} "
                f"and {HUMIDITY_RANGE[1]}"
            )

    if "battery" in data and data["battery"] is not None:
        if not _is_integer(data["battery"]):
            errors.append("battery must be an integer")
        elif not BATTERY_RANGE[0] <= data["battery"] <= BATTERY_RANGE[1]:
            errors.append(
                f"battery must be between {BATTERY_RANGE[0]} "
                f"and {BATTERY_RANGE[1]}"
            )

    return errors
