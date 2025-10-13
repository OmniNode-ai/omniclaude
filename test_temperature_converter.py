#!/usr/bin/env python3
"""
Tests for temperature converter with validation examples.
"""

import pytest
from temperature_converter import TemperatureConverter


def test_celsius_to_fahrenheit():
    """Test Celsius to Fahrenheit conversion."""
    converter = TemperatureConverter()

    # Freezing point of water
    assert converter.celsius_to_fahrenheit(0) == 32.0

    # Boiling point of water
    assert converter.celsius_to_fahrenheit(100) == 212.0

    # Room temperature
    assert abs(converter.celsius_to_fahrenheit(20) - 68.0) < 0.01

    # Negative temperature
    assert converter.celsius_to_fahrenheit(-40) == -40.0


def test_fahrenheit_to_celsius():
    """Test Fahrenheit to Celsius conversion."""
    converter = TemperatureConverter()

    # Freezing point of water
    assert converter.fahrenheit_to_celsius(32) == 0.0

    # Boiling point of water
    assert converter.fahrenheit_to_celsius(212) == 100.0

    # Room temperature
    assert abs(converter.fahrenheit_to_celsius(68) - 20.0) < 0.01

    # Negative temperature
    assert converter.fahrenheit_to_celsius(-40) == -40.0


def test_absolute_zero_validation_celsius():
    """Test validation for temperatures below absolute zero (Celsius)."""
    converter = TemperatureConverter()

    with pytest.raises(ValueError, match="absolute zero"):
        converter.celsius_to_fahrenheit(-300)


def test_absolute_zero_validation_fahrenheit():
    """Test validation for temperatures below absolute zero (Fahrenheit)."""
    converter = TemperatureConverter()

    with pytest.raises(ValueError, match="absolute zero"):
        converter.fahrenheit_to_celsius(-500)


def test_input_validation():
    """Test input validation."""
    converter = TemperatureConverter()

    # Valid inputs
    assert converter.validate_input("25.5") == 25.5
    assert converter.validate_input("-10") == -10.0
    assert converter.validate_input("  100  ") == 100.0

    # Invalid inputs
    assert converter.validate_input("abc") is None
    assert converter.validate_input("") is None
    assert converter.validate_input("12.34.56") is None


def test_round_trip_conversion():
    """Test that converting back and forth returns original value."""
    converter = TemperatureConverter()

    original_c = 25.0
    fahrenheit = converter.celsius_to_fahrenheit(original_c)
    back_to_celsius = converter.fahrenheit_to_celsius(fahrenheit)

    assert abs(back_to_celsius - original_c) < 0.0001


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
