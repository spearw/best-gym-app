"""Weights are stored as exact kg decimals. Convert only at the edges: when a person
types a number in their own unit, and when one is shown to them."""

from decimal import ROUND_HALF_UP, Decimal

KG_PER_LB = Decimal("0.45359237")


def to_kg(value, units):
    value = Decimal(value)
    if units == "lb":
        value = value * KG_PER_LB
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def from_kg(kg, units):
    kg = Decimal(kg)
    if units == "lb":
        return (kg / KG_PER_LB).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return kg.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def display(kg, units):
    """'82.5 kg' or '181.9 lb', with trailing zeros dropped."""
    if kg is None:
        return ""
    value = from_kg(kg, units).normalize()
    text = format(value, "f")
    return f"{text} {units}"
