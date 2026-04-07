"""
Deterministic math library — Decimal-based arithmetic with provenance tracking.

Every function:
- Takes STRING inputs (not float) to prevent IEEE 754 corruption
- Returns STRING outputs via Decimal
- Returns a provenance envelope: {result, formula, inputs, computation_id}
- Uses ROUND_HALF_EVEN (banker's rounding)

This module has zero dependencies on LLM, FastAPI, or any external service.
"""
import uuid
from decimal import Decimal, getcontext, ROUND_HALF_EVEN, InvalidOperation
from typing import Any

# Set global precision — 28 significant digits is more than enough for enterprise finance
getcontext().prec = 28
getcontext().rounding = ROUND_HALF_EVEN


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_decimal(value: str | int | float) -> Decimal:
    """Safely convert any numeric input to Decimal. Strips currency symbols and commas."""
    if isinstance(value, Decimal):
        return value
    s = str(value).strip().replace(",", "").replace("$", "").replace("£", "").replace("€", "")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"Cannot convert '{value}' to Decimal: {e}")


def _envelope(result: Decimal | str | bool, formula: str, inputs: dict, **extra) -> dict:
    """Standard provenance wrapper for all math outputs."""
    return {
        "result": str(result),
        "formula": formula,
        "inputs": {k: str(v) for k, v in inputs.items()},
        "computation_id": str(uuid.uuid4()),
        **extra,
    }


def _quantize(value: Decimal, places: int = 10) -> Decimal:
    """Quantize to N decimal places, producing clean output."""
    quantizer = Decimal(10) ** -places
    q = value.quantize(quantizer)
    # Convert to string, strip trailing zeros after decimal point, strip trailing dot
    s = str(q)
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return Decimal(s)


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------

def decimal_add(a: str, b: str) -> dict:
    """Add two numbers. Returns exact sum."""
    da, db = _to_decimal(a), _to_decimal(b)
    result = da + db
    return _envelope(result, f"{da} + {db}", {"a": da, "b": db})


def decimal_subtract(a: str, b: str) -> dict:
    """Subtract b from a. Returns exact difference."""
    da, db = _to_decimal(a), _to_decimal(b)
    result = da - db
    return _envelope(result, f"{da} - {db}", {"a": da, "b": db})


def decimal_multiply(a: str, b: str) -> dict:
    """Multiply two numbers. Returns exact product."""
    da, db = _to_decimal(a), _to_decimal(b)
    result = da * db
    return _envelope(result, f"{da} × {db}", {"a": da, "b": db})


def decimal_divide(a: str, b: str, precision: int = 10) -> dict:
    """Divide a by b. Raises ValueError on division by zero."""
    da, db = _to_decimal(a), _to_decimal(b)
    if db == 0:
        raise ValueError("Division by zero")
    result = _quantize(da / db, precision)
    return _envelope(result, f"{da} ÷ {db}", {"a": da, "b": db}, precision=precision)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def decimal_sum(values: list[str]) -> dict:
    """Sum a list of numbers. Returns exact total."""
    decimals = [_to_decimal(v) for v in values]
    result = sum(decimals, Decimal("0"))
    formula = " + ".join(str(d) for d in decimals[:5])
    if len(decimals) > 5:
        formula += f" + ... ({len(decimals)} values)"
    return _envelope(result, f"sum({formula})", {"values": decimals, "count": len(decimals)})


def decimal_average(values: list[str]) -> dict:
    """Compute arithmetic mean. Returns exact average."""
    if not values:
        raise ValueError("Cannot average empty list")
    decimals = [_to_decimal(v) for v in values]
    total = sum(decimals, Decimal("0"))
    count = Decimal(len(decimals))
    result = _quantize(total / count)
    return _envelope(
        result,
        f"sum({len(decimals)} values) ÷ {count}",
        {"values": decimals, "count": len(decimals), "total": total},
    )


def decimal_weighted_average(values: list[str], weights: list[str]) -> dict:
    """Compute weighted average: Σ(value × weight) ÷ Σ(weights)."""
    if len(values) != len(weights):
        raise ValueError(f"values ({len(values)}) and weights ({len(weights)}) must have same length")
    if not values:
        raise ValueError("Cannot compute weighted average of empty list")

    d_values = [_to_decimal(v) for v in values]
    d_weights = [_to_decimal(w) for w in weights]

    weighted_sum = sum(v * w for v, w in zip(d_values, d_weights))
    total_weight = sum(d_weights, Decimal("0"))

    if total_weight == 0:
        raise ValueError("Total weight is zero")

    result = _quantize(weighted_sum / total_weight)
    return _envelope(
        result,
        "Σ(value × weight) ÷ Σ(weights)",
        {"values": d_values, "weights": d_weights, "weighted_sum": weighted_sum, "total_weight": total_weight},
    )


# ---------------------------------------------------------------------------
# Percentages
# ---------------------------------------------------------------------------

def decimal_percentage(part: str, whole: str) -> dict:
    """What percent is 'part' of 'whole'? Returns (part ÷ whole) × 100."""
    d_part, d_whole = _to_decimal(part), _to_decimal(whole)
    if d_whole == 0:
        raise ValueError("Cannot compute percentage: whole is zero")
    result = _quantize(d_part / d_whole * Decimal("100"))
    return _envelope(
        result,
        f"({d_part} ÷ {d_whole}) × 100",
        {"part": d_part, "whole": d_whole},
        unit="%",
    )


def decimal_percentage_change(old_value: str, new_value: str) -> dict:
    """Percentage change from old to new: ((new - old) ÷ old) × 100."""
    d_old, d_new = _to_decimal(old_value), _to_decimal(new_value)
    if d_old == 0:
        raise ValueError("Cannot compute percentage change: old value is zero")
    change = d_new - d_old
    pct = _quantize(change / d_old * Decimal("100"))
    direction = "increase" if change > 0 else "decrease" if change < 0 else "no change"
    return _envelope(
        pct,
        f"(({d_new} - {d_old}) ÷ {d_old}) × 100",
        {"old_value": d_old, "new_value": d_new, "absolute_change": change},
        direction=direction,
        absolute_change=str(change),
        unit="%",
    )


# ---------------------------------------------------------------------------
# Financial
# ---------------------------------------------------------------------------

def decimal_variance(actual: str, budget: str) -> dict:
    """
    Compute variance: actual - budget.
    Returns absolute variance + percentage variance + direction (favorable/unfavorable).
    """
    d_actual, d_budget = _to_decimal(actual), _to_decimal(budget)
    absolute = d_actual - d_budget
    if d_budget != 0:
        pct = _quantize(absolute / d_budget * Decimal("100"))
    else:
        pct = Decimal("0")

    # For revenue: positive = favorable. For costs: depends on context.
    # We report direction as over/under and let the LLM interpret.
    direction = "over_budget" if absolute > 0 else "under_budget" if absolute < 0 else "on_budget"

    return _envelope(
        absolute,
        f"{d_actual} - {d_budget}",
        {"actual": d_actual, "budget": d_budget},
        percentage=str(pct),
        direction=direction,
    )


def decimal_compound_growth(principal: str, rate: str, periods: int) -> dict:
    """Compound growth: principal × (1 + rate)^periods. Rate as decimal (0.05 = 5%)."""
    d_principal = _to_decimal(principal)
    d_rate = _to_decimal(rate)
    d_periods = Decimal(periods)

    factor = (Decimal("1") + d_rate) ** d_periods
    result = _quantize(d_principal * factor)

    return _envelope(
        result,
        f"{d_principal} × (1 + {d_rate})^{periods}",
        {"principal": d_principal, "rate": d_rate, "periods": periods, "growth_factor": factor},
    )


def decimal_margin(revenue: str, cost: str) -> dict:
    """Compute margin: ((revenue - cost) ÷ revenue) × 100."""
    d_rev, d_cost = _to_decimal(revenue), _to_decimal(cost)
    if d_rev == 0:
        raise ValueError("Cannot compute margin: revenue is zero")
    profit = d_rev - d_cost
    margin = _quantize(profit / d_rev * Decimal("100"))
    return _envelope(
        margin,
        f"(({d_rev} - {d_cost}) ÷ {d_rev}) × 100",
        {"revenue": d_rev, "cost": d_cost, "profit": profit},
        unit="%",
    )


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def decimal_rank(items: list[dict], key: str, order: str = "desc") -> dict:
    """
    Rank a list of items by a numeric key.
    items: [{"name": "A", "revenue": "500"}, ...]
    Returns ranked list with position field added.
    """
    if not items:
        return _envelope("[]", f"rank by {key}", {"items": [], "key": key})

    def sort_key(item):
        try:
            return _to_decimal(item.get(key, "0"))
        except (ValueError, InvalidOperation):
            return Decimal("0")

    reverse = order.lower() == "desc"
    sorted_items = sorted(items, key=sort_key, reverse=reverse)

    ranked = []
    for i, item in enumerate(sorted_items, 1):
        ranked.append({**item, "_rank": i, "_value": str(sort_key(item))})

    return _envelope(
        str(len(ranked)),
        f"rank {len(items)} items by '{key}' {order}",
        {"key": key, "order": order, "count": len(items)},
        ranked_items=ranked,
    )


def decimal_threshold_check(value: str, threshold: str, operator: str = "gt") -> dict:
    """
    Check if value meets a threshold.
    operator: gt (>), gte (>=), lt (<), lte (<=), eq (==)
    """
    d_val = _to_decimal(value)
    d_thresh = _to_decimal(threshold)

    ops = {
        "gt": (d_val > d_thresh, ">"),
        "gte": (d_val >= d_thresh, ">="),
        "lt": (d_val < d_thresh, "<"),
        "lte": (d_val <= d_thresh, "<="),
        "eq": (d_val == d_thresh, "=="),
    }

    if operator not in ops:
        raise ValueError(f"Unknown operator: {operator}. Use: gt, gte, lt, lte, eq")

    result, symbol = ops[operator]
    return _envelope(
        result,
        f"{d_val} {symbol} {d_thresh}",
        {"value": d_val, "threshold": d_thresh, "operator": operator},
        met=result,
    )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def decimal_round(value: str, places: int = 2) -> dict:
    """Round to N decimal places using banker's rounding (ROUND_HALF_EVEN)."""
    d_val = _to_decimal(value)
    quantizer = Decimal(10) ** -places
    result = d_val.quantize(quantizer, rounding=ROUND_HALF_EVEN)
    return _envelope(
        result,
        f"round({d_val}, {places})",
        {"value": d_val, "places": places},
        rounding_method="ROUND_HALF_EVEN",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SPECIALIST FINANCIAL TOOLS — CFO-grade calculations
# ═══════════════════════════════════════════════════════════════════════════════

# ---------------------------------------------------------------------------
# Valuation & Investment
# ---------------------------------------------------------------------------

def decimal_npv(rate: str, cashflows: list[str]) -> dict:
    """Net Present Value: sum of CF_i / (1+r)^i. cashflows[0] is period 0 (often negative = investment)."""
    r = _to_decimal(rate)
    if r <= Decimal("-1"):
        raise ValueError("Discount rate must be > -100%")
    total = Decimal("0")
    details = []
    for i, cf in enumerate(cashflows):
        d_cf = _to_decimal(cf)
        factor = (Decimal("1") + r) ** i
        pv = _quantize(d_cf / factor)
        total += pv
        details.append({"period": i, "cashflow": str(d_cf), "pv": str(pv)})
    return _envelope(
        _quantize(total),
        f"sum(CF_i / (1+{r})^i) for i=0..{len(cashflows)-1}",
        {"rate": str(r), "cashflows": [str(_to_decimal(c)) for c in cashflows]},
        period_details=details,
    )


def decimal_irr(cashflows: list[str], max_iterations: int = 100, tolerance: str = "0.000001") -> dict:
    """Internal Rate of Return via Newton-Raphson. cashflows[0] is typically negative (investment)."""
    cfs = [_to_decimal(c) for c in cashflows]
    tol = _to_decimal(tolerance)
    guess = Decimal("0.10")  # start at 10%

    for iteration in range(max_iterations):
        npv_val = sum(cf / (Decimal("1") + guess) ** i for i, cf in enumerate(cfs))
        # Derivative: sum(-i * cf / (1+r)^(i+1))
        dnpv = sum(Decimal(-i) * cf / (Decimal("1") + guess) ** (i + 1) for i, cf in enumerate(cfs))
        if dnpv == 0:
            break
        new_guess = guess - npv_val / dnpv
        if abs(new_guess - guess) < tol:
            guess = new_guess
            break
        guess = new_guess

    result_pct = _quantize(guess * Decimal("100"))
    return _envelope(
        result_pct,
        f"IRR where NPV=0, solved in {min(iteration+1, max_iterations)} iterations",
        {"cashflows": [str(c) for c in cfs]},
        unit="%",
        rate_decimal=str(_quantize(guess, 6)),
        converged=iteration < max_iterations - 1,
    )


def decimal_payback_period(initial_investment: str, annual_cashflow: str) -> dict:
    """Simple payback period = investment / annual cashflow."""
    inv = _to_decimal(initial_investment)
    cf = _to_decimal(annual_cashflow)
    if cf <= 0:
        raise ValueError("Annual cashflow must be positive")
    result = _quantize(inv / cf, 2)
    return _envelope(
        result,
        f"{inv} / {cf}",
        {"initial_investment": str(inv), "annual_cashflow": str(cf)},
        unit="years",
    )


def decimal_roi(gain: str, cost: str) -> dict:
    """Return on Investment: ((gain - cost) / cost) × 100."""
    d_gain = _to_decimal(gain)
    d_cost = _to_decimal(cost)
    if d_cost == 0:
        raise ValueError("Cost cannot be zero")
    result = _quantize((d_gain - d_cost) / d_cost * Decimal("100"))
    return _envelope(
        result,
        f"(({d_gain} - {d_cost}) / {d_cost}) × 100",
        {"gain": str(d_gain), "cost": str(d_cost)},
        unit="%",
    )


def decimal_cagr(begin_value: str, end_value: str, periods: int) -> dict:
    """Compound Annual Growth Rate: (end/begin)^(1/n) - 1."""
    d_begin = _to_decimal(begin_value)
    d_end = _to_decimal(end_value)
    if d_begin <= 0:
        raise ValueError("Begin value must be positive")
    if periods <= 0:
        raise ValueError("Periods must be positive")
    # Use float for fractional exponent, then convert back
    import math
    ratio = float(d_end / d_begin)
    rate = ratio ** (1.0 / periods) - 1.0
    result_pct = _quantize(Decimal(str(rate)) * Decimal("100"))
    return _envelope(
        result_pct,
        f"(({d_end}/{d_begin})^(1/{periods}) - 1) × 100",
        {"begin_value": str(d_begin), "end_value": str(d_end), "periods": periods},
        unit="%",
        rate_decimal=str(_quantize(Decimal(str(rate)), 6)),
    )


# ---------------------------------------------------------------------------
# Liquidity & Leverage Ratios
# ---------------------------------------------------------------------------

def decimal_current_ratio(current_assets: str, current_liabilities: str) -> dict:
    """Current Ratio = Current Assets / Current Liabilities."""
    ca = _to_decimal(current_assets)
    cl = _to_decimal(current_liabilities)
    if cl == 0:
        raise ValueError("Current liabilities cannot be zero")
    result = _quantize(ca / cl, 2)
    return _envelope(
        result,
        f"{ca} / {cl}",
        {"current_assets": str(ca), "current_liabilities": str(cl)},
        healthy="True" if result >= Decimal("1.5") else "False",
    )


def decimal_quick_ratio(current_assets: str, inventory: str, current_liabilities: str) -> dict:
    """Quick Ratio = (Current Assets - Inventory) / Current Liabilities."""
    ca = _to_decimal(current_assets)
    inv = _to_decimal(inventory)
    cl = _to_decimal(current_liabilities)
    if cl == 0:
        raise ValueError("Current liabilities cannot be zero")
    result = _quantize((ca - inv) / cl, 2)
    return _envelope(
        result,
        f"({ca} - {inv}) / {cl}",
        {"current_assets": str(ca), "inventory": str(inv), "current_liabilities": str(cl)},
        healthy="True" if result >= Decimal("1.0") else "False",
    )


def decimal_debt_to_equity(total_debt: str, total_equity: str) -> dict:
    """Debt-to-Equity Ratio = Total Debt / Total Equity."""
    debt = _to_decimal(total_debt)
    equity = _to_decimal(total_equity)
    if equity == 0:
        raise ValueError("Total equity cannot be zero")
    result = _quantize(debt / equity, 2)
    return _envelope(
        result,
        f"{debt} / {equity}",
        {"total_debt": str(debt), "total_equity": str(equity)},
    )


def decimal_working_capital(current_assets: str, current_liabilities: str) -> dict:
    """Working Capital = Current Assets - Current Liabilities."""
    ca = _to_decimal(current_assets)
    cl = _to_decimal(current_liabilities)
    result = ca - cl
    return _envelope(
        _quantize(result),
        f"{ca} - {cl}",
        {"current_assets": str(ca), "current_liabilities": str(cl)},
        positive="True" if result > 0 else "False",
    )


# ---------------------------------------------------------------------------
# Efficiency Ratios
# ---------------------------------------------------------------------------

def decimal_dso(receivables: str, revenue: str, days: int = 365) -> dict:
    """Days Sales Outstanding = (Receivables / Revenue) × Days."""
    rec = _to_decimal(receivables)
    rev = _to_decimal(revenue)
    if rev == 0:
        raise ValueError("Revenue cannot be zero")
    result = _quantize(rec / rev * Decimal(str(days)), 1)
    return _envelope(
        result,
        f"({rec} / {rev}) × {days}",
        {"receivables": str(rec), "revenue": str(rev), "days": days},
        unit="days",
    )


# ---------------------------------------------------------------------------
# Profitability
# ---------------------------------------------------------------------------

def decimal_ebitda(revenue: str, cogs: str, opex: str, depreciation: str = "0") -> dict:
    """EBITDA = Revenue - COGS - OpEx + Depreciation & Amortization."""
    rev = _to_decimal(revenue)
    d_cogs = _to_decimal(cogs)
    d_opex = _to_decimal(opex)
    da = _to_decimal(depreciation)
    result = rev - d_cogs - d_opex + da
    return _envelope(
        _quantize(result),
        f"{rev} - {d_cogs} - {d_opex} + {da}",
        {"revenue": str(rev), "cogs": str(d_cogs), "opex": str(d_opex), "depreciation": str(da)},
    )


def decimal_gross_margin(revenue: str, cogs: str) -> dict:
    """Gross Margin % = ((Revenue - COGS) / Revenue) × 100."""
    rev = _to_decimal(revenue)
    d_cogs = _to_decimal(cogs)
    if rev == 0:
        raise ValueError("Revenue cannot be zero")
    result = _quantize((rev - d_cogs) / rev * Decimal("100"))
    return _envelope(result, f"(({rev} - {d_cogs}) / {rev}) × 100", {"revenue": str(rev), "cogs": str(d_cogs)}, unit="%")


def decimal_operating_margin(operating_income: str, revenue: str) -> dict:
    """Operating Margin % = (Operating Income / Revenue) × 100."""
    oi = _to_decimal(operating_income)
    rev = _to_decimal(revenue)
    if rev == 0:
        raise ValueError("Revenue cannot be zero")
    result = _quantize(oi / rev * Decimal("100"))
    return _envelope(result, f"({oi} / {rev}) × 100", {"operating_income": str(oi), "revenue": str(rev)}, unit="%")


def decimal_roe(net_income: str, equity: str) -> dict:
    """Return on Equity = (Net Income / Equity) × 100."""
    ni = _to_decimal(net_income)
    eq = _to_decimal(equity)
    if eq == 0:
        raise ValueError("Equity cannot be zero")
    result = _quantize(ni / eq * Decimal("100"))
    return _envelope(result, f"({ni} / {eq}) × 100", {"net_income": str(ni), "equity": str(eq)}, unit="%")


def decimal_roa(net_income: str, total_assets: str) -> dict:
    """Return on Assets = (Net Income / Total Assets) × 100."""
    ni = _to_decimal(net_income)
    ta = _to_decimal(total_assets)
    if ta == 0:
        raise ValueError("Total assets cannot be zero")
    result = _quantize(ni / ta * Decimal("100"))
    return _envelope(result, f"({ni} / {ta}) × 100", {"net_income": str(ni), "total_assets": str(ta)}, unit="%")


# ---------------------------------------------------------------------------
# FX
# ---------------------------------------------------------------------------

def decimal_fx_convert(amount: str, rate: str) -> dict:
    """Convert currency: amount × rate."""
    d_amount = _to_decimal(amount)
    d_rate = _to_decimal(rate)
    result = _quantize(d_amount * d_rate, 2)
    return _envelope(
        result,
        f"{d_amount} × {d_rate}",
        {"amount": str(d_amount), "rate": str(d_rate)},
    )
