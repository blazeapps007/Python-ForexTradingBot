from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP


def decimals(step):
    """Number of decimal places in a tick or step size, e.g. 0.001 -> 3, 1 -> 0."""
    exponent = Decimal(str(step)).normalize().as_tuple().exponent
    return max(0, -exponent)


def _to_step(value, step, rounding):
    step_d = Decimal(str(step))
    return float((Decimal(str(value)) / step_d).to_integral_value(rounding=rounding) * step_d)


def round_to_step(value, step):
    return _to_step(value, step, ROUND_HALF_UP)


def floor_to_step(value, step):
    return _to_step(value, step, ROUND_FLOOR)
