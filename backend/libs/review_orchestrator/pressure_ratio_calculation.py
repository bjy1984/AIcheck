"""Compare recorded decimal ratios exactly; float output is presentation only."""
import math
import re
from fractions import Fraction


def _number(value):
    if type(value) not in (str, int, float) or len(str(value)) > 128:
        return None
    if not re.fullmatch(r"\d+(?:\.\d+)?(?:[eE][+-]?\d{1,3})?", str(value)):
        return None
    try:
        parsed = Fraction(str(value))
        return parsed if parsed >= 0 else None
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def pressure_ratio_calculation(explicit, pressure, design_pressure, minimum, maximum):
    ratio = _number(explicit)
    if explicit is None:
        actual, design = _number(pressure), _number(design_pressure)
        ratio = actual / design if actual is not None and design is not None and design > 0 else None
    if ratio is None:
        return None, None, None
    try:
        display = float(ratio)
    except OverflowError:
        return None, None, None
    if not math.isfinite(display):
        return None, None, None
    lower, upper = _number(minimum), _number(maximum)
    return display, ratio >= lower if lower is not None else None, ratio > upper if upper is not None else None
