"""Production-quality calculator module with add and subtract functions.

This module provides basic arithmetic operations with proper type checking,
error handling, and comprehensive documentation.
"""

from typing import Union


class CalculatorError(Exception):
    """Custom exception for calculator-related errors."""

    pass


def add(a: Union[int, float], b: Union[int, float]) -> float:
    """
    Add two numbers together.

    Args:
        a: First number (int or float)
        b: Second number (int or float)

    Returns:
        Sum of a and b as a float

    Raises:
        CalculatorError: If either argument is not a number
        TypeError: If arguments are of invalid type

    Examples:
        >>> add(2, 3)
        5.0
        >>> add(-5, 10)
        5.0
        >>> add(3.14, 2.86)
        6.0
    """
    try:
        # Validate input types
        if not isinstance(a, (int, float)) or isinstance(a, bool):
            raise CalculatorError(f"First argument must be a number, got {type(a).__name__}")
        if not isinstance(b, (int, float)) or isinstance(b, bool):
            raise CalculatorError(f"Second argument must be a number, got {type(b).__name__}")

        return float(a + b)
    except (TypeError, ValueError) as e:
        raise CalculatorError(f"Error performing addition: {str(e)}") from e


def subtract(a: Union[int, float], b: Union[int, float]) -> float:
    """
    Subtract second number from first number.

    Args:
        a: Number to subtract from (int or float)
        b: Number to subtract (int or float)

    Returns:
        Difference of a minus b as a float

    Raises:
        CalculatorError: If either argument is not a number
        TypeError: If arguments are of invalid type

    Examples:
        >>> subtract(10, 3)
        7.0
        >>> subtract(5, 10)
        -5.0
        >>> subtract(3.14, 1.14)
        2.0
    """
    try:
        # Validate input types
        if not isinstance(a, (int, float)) or isinstance(a, bool):
            raise CalculatorError(f"First argument must be a number, got {type(a).__name__}")
        if not isinstance(b, (int, float)) or isinstance(b, bool):
            raise CalculatorError(f"Second argument must be a number, got {type(b).__name__}")

        return float(a - b)
    except (TypeError, ValueError) as e:
        raise CalculatorError(f"Error performing subtraction: {str(e)}") from e


if __name__ == "__main__":
    print("=== Calculator Module Demo ===\n")

    # Addition examples
    print("Addition Examples:")
    print(f"add(2, 3) = {add(2, 3)}")
    print(f"add(-5, 10) = {add(-5, 10)}")
    print(f"add(3.14, 2.86) = {add(3.14, 2.86)}")
    print(f"add(100, 0.5) = {add(100, 0.5)}")

    print("\nSubtraction Examples:")
    print(f"subtract(10, 3) = {subtract(10, 3)}")
    print(f"subtract(5, 10) = {subtract(5, 10)}")
    print(f"subtract(3.14, 1.14) = {subtract(3.14, 1.14)}")
    print(f"subtract(100, 100) = {subtract(100, 100)}")

    # Error handling examples
    print("\nError Handling Examples:")
    try:
        result = add("5", 3)
        print(f"add('5', 3) = {result}")
    except CalculatorError as e:
        print(f"add('5', 3) raised CalculatorError: {e}")

    try:
        result = subtract(10, "abc")
        print(f"subtract(10, 'abc') = {result}")
    except CalculatorError as e:
        print(f"subtract(10, 'abc') raised CalculatorError: {e}")

    try:
        result = add(None, 5)
        print(f"add(None, 5) = {result}")
    except CalculatorError as e:
        print(f"add(None, 5) raised CalculatorError: {e}")

    print("\n=== Demo Complete ===")
