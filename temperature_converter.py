#!/usr/bin/env python3
"""Temperature conversion utilities.

This module provides temperature conversion functions between Celsius and Fahrenheit.
"""


def celsius_to_fahrenheit(celsius: float) -> float:
    """Convert Celsius to Fahrenheit.

    Uses the standard conversion formula: F = (C × 9/5) + 32

    Args:
        celsius: Temperature in degrees Celsius

    Returns:
        Temperature in degrees Fahrenheit

    Raises:
        TypeError: If celsius is not a numeric type
        ValueError: If temperature is below absolute zero (-273.15°C)

    Examples:
        >>> celsius_to_fahrenheit(0)
        32.0
        >>> celsius_to_fahrenheit(100)
        212.0
        >>> celsius_to_fahrenheit(-40)
        -40.0
    """
    # Type validation
    if not isinstance(celsius, (int, float)):
        raise TypeError(
            f"celsius must be a numeric type, got {type(celsius).__name__}"
        )

    # Physical validation - absolute zero in Celsius
    ABSOLUTE_ZERO_C = -273.15
    if celsius < ABSOLUTE_ZERO_C:
        raise ValueError(
            f"Temperature {celsius}°C is below absolute zero ({ABSOLUTE_ZERO_C}°C)"
        )

    # Conversion formula
    return (celsius * 9/5) + 32


def fahrenheit_to_celsius(fahrenheit: float) -> float:
    """Convert Fahrenheit to Celsius.

    Uses the standard conversion formula: C = (F - 32) × 5/9

    Args:
        fahrenheit: Temperature in degrees Fahrenheit

    Returns:
        Temperature in degrees Celsius

    Raises:
        TypeError: If fahrenheit is not a numeric type
        ValueError: If temperature is below absolute zero (-459.67°F)

    Examples:
        >>> fahrenheit_to_celsius(32)
        0.0
        >>> fahrenheit_to_celsius(212)
        100.0
        >>> fahrenheit_to_celsius(-40)
        -40.0
    """
    # Type validation
    if not isinstance(fahrenheit, (int, float)):
        raise TypeError(
            f"fahrenheit must be a numeric type, got {type(fahrenheit).__name__}"
        )

    # Physical validation - absolute zero in Fahrenheit
    ABSOLUTE_ZERO_F = -459.67
    if fahrenheit < ABSOLUTE_ZERO_F:
        raise ValueError(
            f"Temperature {fahrenheit}°F is below absolute zero ({ABSOLUTE_ZERO_F}°F)"
        )

    # Conversion formula
    return (fahrenheit - 32) * 5/9


if __name__ == "__main__":
    # Example usage
    print("Temperature Conversion Examples")
    print("=" * 40)

    # Celsius to Fahrenheit conversions
    print("\nCelsius to Fahrenheit:")
    test_temps_c = [0, 25, 100, -40, 37]
    for temp_c in test_temps_c:
        temp_f = celsius_to_fahrenheit(temp_c)
        print(f"{temp_c:>6.1f}°C = {temp_f:>6.1f}°F")

    # Fahrenheit to Celsius conversions
    print("\nFahrenheit to Celsius:")
    test_temps_f = [32, 77, 212, -40, 98.6]
    for temp_f in test_temps_f:
        temp_c = fahrenheit_to_celsius(temp_f)
        print(f"{temp_f:>6.1f}°F = {temp_c:>6.1f}°C")

    # Error handling demonstration
    print("\nError Handling Examples:")
    try:
        celsius_to_fahrenheit(-300)
    except ValueError as e:
        print(f"✗ ValueError: {e}")

    try:
        celsius_to_fahrenheit("invalid")
    except TypeError as e:
        print(f"✗ TypeError: {e}")
