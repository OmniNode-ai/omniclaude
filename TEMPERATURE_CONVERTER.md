# Temperature Converter

A simple, robust temperature converter with input validation.

## Features

- Bidirectional conversion between Celsius and Fahrenheit
- Input validation (numeric values only)
- Physical limit validation (prevents temperatures below absolute zero)
- Interactive CLI interface
- Comprehensive test suite

## Usage

### Interactive Mode

```bash
python temperature_converter.py
```

The interactive menu allows you to:
1. Convert Celsius to Fahrenheit
2. Convert Fahrenheit to Celsius
3. Exit

### Programmatic Usage

```python
from temperature_converter import TemperatureConverter

converter = TemperatureConverter()

# Convert Celsius to Fahrenheit
fahrenheit = converter.celsius_to_fahrenheit(25.0)
print(f"25°C = {fahrenheit}°F")  # Output: 25°C = 77.0°F

# Convert Fahrenheit to Celsius
celsius = converter.fahrenheit_to_celsius(77.0)
print(f"77°F = {celsius}°C")  # Output: 77°F = 25.0°C
```

## Input Validation

The converter includes two levels of validation:

1. **Type Validation**: Ensures input is numeric
   - Accepts integers and floats
   - Trims whitespace
   - Rejects non-numeric strings

2. **Physical Limit Validation**: Prevents impossible temperatures
   - Celsius: Must be >= -273.15°C (absolute zero)
   - Fahrenheit: Must be >= -459.67°F (absolute zero)

## Testing

Run the test suite:

```bash
python test_temperature_converter.py
```

Or with pytest:

```bash
pytest test_temperature_converter.py -v
```

## Examples

### Valid Conversions
- 0°C = 32°F (freezing point of water)
- 100°C = 212°F (boiling point of water)
- -40°C = -40°F (same in both scales)
- 25°C = 77°F (room temperature)

### Invalid Inputs
- Non-numeric values: "abc", "12.34.56"
- Below absolute zero: -300°C, -500°F
- Empty strings

## Implementation Details

- Pure Python implementation
- No external dependencies for core functionality
- pytest required for running tests
- Follows ONEX architecture patterns with clear separation of concerns
