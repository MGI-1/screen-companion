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


def decimal_filter_by_threshold(items: list[dict], key: str, threshold: str,
                                operator: str = "gt") -> dict:
    """
    Return only items whose `key` field meets the threshold.
    items: [{"name": "A", "amount": "500"}, ...]
    operator: gt, gte, lt, lte, eq
    """
    if not items:
        return _envelope(
            "0",
            f"filter by {key} {operator} {threshold}",
            {"key": key, "threshold": threshold, "operator": operator},
            filtered_items=[],
            filtered_count=0,
            input_count=0,
        )

    d_thresh = _to_decimal(threshold)
    ops = {
        "gt": lambda v: v > d_thresh,
        "gte": lambda v: v >= d_thresh,
        "lt": lambda v: v < d_thresh,
        "lte": lambda v: v <= d_thresh,
        "eq": lambda v: v == d_thresh,
    }
    if operator not in ops:
        raise ValueError(f"Unknown operator: {operator}. Use: gt, gte, lt, lte, eq")
    op_fn = ops[operator]

    filtered = []
    skipped = 0
    for item in items:
        try:
            val = _to_decimal(item.get(key, "0"))
        except (ValueError, InvalidOperation):
            skipped += 1
            continue
        if op_fn(val):
            filtered.append({**item, "_value": str(val)})

    return _envelope(
        str(len(filtered)),
        f"filter {len(items)} items where {key} {operator} {threshold}",
        {
            "key": key,
            "threshold": str(d_thresh),
            "operator": operator,
            "input_count": len(items),
            "skipped_non_numeric": skipped,
        },
        filtered_items=filtered,
        filtered_count=len(filtered),
    )


def decimal_top_n(items: list[dict], key: str, n: int, order: str = "desc") -> dict:
    """
    Return the top-N items by a numeric key (sort + slice in one call).
    items: [{"name": "A", "revenue": "500"}, ...]
    order: "desc" (largest first) or "asc" (smallest first)
    """
    n_int = int(n)
    ranked = decimal_rank(items, key, order)
    top = ranked.get("ranked_items", [])[:n_int]
    return _envelope(
        str(len(top)),
        f"top {n_int} of {len(items)} by '{key}' {order}",
        {
            "key": key,
            "order": order,
            "n": n_int,
            "input_count": len(items),
        },
        top_items=top,
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


# ═══════════════════════════════════════════════════════════════════════════════
# EXTENDED SPECIALIST TOOLS — Time series, working capital, advanced valuation
# ═══════════════════════════════════════════════════════════════════════════════

# ---------------------------------------------------------------------------
# Working capital cycle
# ---------------------------------------------------------------------------

def decimal_dpo(payables: str, cogs: str, days: int = 365) -> dict:
    """Days Payable Outstanding = (Payables / COGS) × Days."""
    pay = _to_decimal(payables)
    d_cogs = _to_decimal(cogs)
    if d_cogs == 0:
        raise ValueError("COGS cannot be zero")
    result = _quantize(pay / d_cogs * Decimal(str(days)), 1)
    return _envelope(
        result,
        f"({pay} / {d_cogs}) × {days}",
        {"payables": str(pay), "cogs": str(d_cogs), "days": days},
        unit="days",
    )


def decimal_dio(inventory: str, cogs: str, days: int = 365) -> dict:
    """Days Inventory Outstanding = (Inventory / COGS) × Days."""
    inv = _to_decimal(inventory)
    d_cogs = _to_decimal(cogs)
    if d_cogs == 0:
        raise ValueError("COGS cannot be zero")
    result = _quantize(inv / d_cogs * Decimal(str(days)), 1)
    return _envelope(
        result,
        f"({inv} / {d_cogs}) × {days}",
        {"inventory": str(inv), "cogs": str(d_cogs), "days": days},
        unit="days",
    )


def decimal_cash_conversion_cycle(dso: str, dio: str, dpo: str) -> dict:
    """Cash Conversion Cycle = DSO + DIO - DPO."""
    d_dso = _to_decimal(dso)
    d_dio = _to_decimal(dio)
    d_dpo = _to_decimal(dpo)
    result = d_dso + d_dio - d_dpo
    return _envelope(
        _quantize(result, 1),
        f"{d_dso} + {d_dio} - {d_dpo}",
        {"dso": str(d_dso), "dio": str(d_dio), "dpo": str(d_dpo)},
        unit="days",
        favorable="True" if result < Decimal("60") else "False",
    )


def decimal_inventory_turnover(cogs: str, average_inventory: str) -> dict:
    """Inventory Turnover = COGS / Average Inventory."""
    d_cogs = _to_decimal(cogs)
    inv = _to_decimal(average_inventory)
    if inv == 0:
        raise ValueError("Average inventory cannot be zero")
    result = _quantize(d_cogs / inv, 2)
    return _envelope(
        result,
        f"{d_cogs} / {inv}",
        {"cogs": str(d_cogs), "average_inventory": str(inv)},
        unit="x per year",
    )


# ---------------------------------------------------------------------------
# Solvency & coverage
# ---------------------------------------------------------------------------

def decimal_interest_coverage(ebitda: str, interest_expense: str) -> dict:
    """Interest Coverage Ratio = EBITDA / Interest Expense."""
    e = _to_decimal(ebitda)
    interest = _to_decimal(interest_expense)
    if interest == 0:
        raise ValueError("Interest expense cannot be zero")
    result = _quantize(e / interest, 2)
    return _envelope(
        result,
        f"{e} / {interest}",
        {"ebitda": str(e), "interest_expense": str(interest)},
        unit="x",
        healthy="True" if result >= Decimal("3.0") else "False",
    )


def decimal_debt_service_coverage(operating_income: str, debt_service: str) -> dict:
    """Debt Service Coverage Ratio = Operating Income / Total Debt Service."""
    oi = _to_decimal(operating_income)
    ds = _to_decimal(debt_service)
    if ds == 0:
        raise ValueError("Debt service cannot be zero")
    result = _quantize(oi / ds, 2)
    return _envelope(
        result,
        f"{oi} / {ds}",
        {"operating_income": str(oi), "debt_service": str(ds)},
        unit="x",
        healthy="True" if result >= Decimal("1.25") else "False",
    )


# ---------------------------------------------------------------------------
# Cost analysis
# ---------------------------------------------------------------------------

def decimal_contribution_margin(revenue: str, variable_costs: str) -> dict:
    """Contribution Margin = Revenue - Variable Costs (and as %)."""
    rev = _to_decimal(revenue)
    vc = _to_decimal(variable_costs)
    if rev == 0:
        raise ValueError("Revenue cannot be zero")
    cm = rev - vc
    cm_pct = _quantize(cm / rev * Decimal("100"))
    return _envelope(
        _quantize(cm),
        f"{rev} - {vc}",
        {"revenue": str(rev), "variable_costs": str(vc)},
        contribution_margin_pct=str(cm_pct),
        unit="$",
    )


def decimal_break_even(fixed_costs: str, price_per_unit: str, variable_cost_per_unit: str) -> dict:
    """Break-even units = Fixed Costs / (Price - Variable Cost per unit)."""
    fc = _to_decimal(fixed_costs)
    price = _to_decimal(price_per_unit)
    vc = _to_decimal(variable_cost_per_unit)
    cm_per_unit = price - vc
    if cm_per_unit <= 0:
        raise ValueError("Contribution margin per unit must be positive")
    units = _quantize(fc / cm_per_unit, 0)
    revenue_at_break_even = _quantize(units * price)
    return _envelope(
        units,
        f"{fc} / ({price} - {vc})",
        {"fixed_costs": str(fc), "price_per_unit": str(price), "variable_cost_per_unit": str(vc)},
        unit="units",
        revenue_at_break_even=str(revenue_at_break_even),
        contribution_per_unit=str(cm_per_unit),
    )


# ---------------------------------------------------------------------------
# Advanced valuation
# ---------------------------------------------------------------------------

def decimal_wacc(equity: str, debt: str, cost_of_equity: str, cost_of_debt: str, tax_rate: str) -> dict:
    """Weighted Average Cost of Capital.
    WACC = (E/V × Re) + (D/V × Rd × (1 - Tc))
    """
    e = _to_decimal(equity)
    d = _to_decimal(debt)
    re = _to_decimal(cost_of_equity)
    rd = _to_decimal(cost_of_debt)
    tc = _to_decimal(tax_rate)
    v = e + d
    if v == 0:
        raise ValueError("Equity + Debt cannot be zero")
    equity_weight = e / v
    debt_weight = d / v
    after_tax_cod = rd * (Decimal("1") - tc)
    wacc = equity_weight * re + debt_weight * after_tax_cod
    result = _quantize(wacc * Decimal("100"))
    return _envelope(
        result,
        f"({e}/{v} × {re}) + ({d}/{v} × {rd} × (1 - {tc}))",
        {
            "equity": str(e), "debt": str(d), "cost_of_equity": str(re),
            "cost_of_debt": str(rd), "tax_rate": str(tc),
        },
        unit="%",
        equity_weight=str(_quantize(equity_weight * Decimal("100"))),
        debt_weight=str(_quantize(debt_weight * Decimal("100"))),
    )


def decimal_xnpv(rate: str, cashflows: list[str], dates: list[str]) -> dict:
    """NPV with irregular dates: sum(CF_i / (1+r)^((d_i - d_0)/365))."""
    from datetime import datetime
    r = _to_decimal(rate)
    if len(cashflows) != len(dates):
        raise ValueError("cashflows and dates must have same length")
    cfs = [_to_decimal(c) for c in cashflows]
    parsed_dates = [datetime.fromisoformat(d) for d in dates]
    d0 = parsed_dates[0]
    total = Decimal("0")
    details = []
    for cf, d in zip(cfs, parsed_dates):
        days = (d - d0).days
        years = Decimal(days) / Decimal("365")
        # For fractional exponent, fall back to float
        factor = Decimal(str(float(Decimal("1") + r) ** float(years)))
        pv = _quantize(cf / factor) if factor != 0 else Decimal("0")
        total += pv
        details.append({"date": d.isoformat(), "cashflow": str(cf), "years": str(_quantize(years, 4)), "pv": str(pv)})
    return _envelope(
        _quantize(total),
        f"sum(CF_i / (1+{r})^((d_i - d_0)/365))",
        {"rate": str(r), "cashflows": [str(c) for c in cfs], "dates": dates},
        period_details=details,
    )


def decimal_xirr(cashflows: list[str], dates: list[str], max_iterations: int = 100, tolerance: str = "0.000001") -> dict:
    """IRR with irregular dates via Newton-Raphson."""
    from datetime import datetime
    cfs = [_to_decimal(c) for c in cashflows]
    parsed_dates = [datetime.fromisoformat(d) for d in dates]
    d0 = parsed_dates[0]
    years = [Decimal((d - d0).days) / Decimal("365") for d in parsed_dates]
    tol = _to_decimal(tolerance)
    guess = 0.10  # work in float for fractional exponents

    for iteration in range(max_iterations):
        npv = sum(float(cf) / (1 + guess) ** float(yr) for cf, yr in zip(cfs, years))
        dnpv = sum(-float(yr) * float(cf) / (1 + guess) ** (float(yr) + 1) for cf, yr in zip(cfs, years))
        if dnpv == 0:
            break
        new_guess = guess - npv / dnpv
        if abs(new_guess - guess) < float(tol):
            guess = new_guess
            break
        guess = new_guess

    result_pct = _quantize(Decimal(str(guess)) * Decimal("100"))
    return _envelope(
        result_pct,
        f"XIRR with {len(cfs)} irregular cashflows, solved in {min(iteration+1, max_iterations)} iterations",
        {"cashflows": [str(c) for c in cfs], "dates": dates},
        unit="%",
        rate_decimal=str(_quantize(Decimal(str(guess)), 6)),
        converged=iteration < max_iterations - 1,
    )


# ---------------------------------------------------------------------------
# Time series & forecasting
# ---------------------------------------------------------------------------

def decimal_moving_average(values: list[str], window: int = 3) -> dict:
    """N-period simple moving average."""
    nums = [_to_decimal(v) for v in values]
    if window <= 0 or window > len(nums):
        raise ValueError(f"Window must be between 1 and {len(nums)}")
    averages = []
    for i in range(window - 1, len(nums)):
        window_sum = sum(nums[i - window + 1:i + 1])
        averages.append(_quantize(window_sum / Decimal(window)))
    return _envelope(
        str(averages[-1]) if averages else "0",
        f"{window}-period simple moving average over {len(nums)} values",
        {"values": [str(n) for n in nums], "window": window},
        series=[str(a) for a in averages],
        latest=str(averages[-1]) if averages else "0",
    )


def decimal_exponential_smoothing(values: list[str], alpha: str = "0.3") -> dict:
    """Exponential smoothing: S_t = α × X_t + (1-α) × S_{t-1}."""
    nums = [_to_decimal(v) for v in values]
    a = _to_decimal(alpha)
    if not (Decimal("0") < a < Decimal("1")):
        raise ValueError("Alpha must be between 0 and 1")
    if not nums:
        raise ValueError("Values list cannot be empty")
    smoothed = [nums[0]]
    for i in range(1, len(nums)):
        s = a * nums[i] + (Decimal("1") - a) * smoothed[-1]
        smoothed.append(_quantize(s))
    forecast_next = _quantize(a * nums[-1] + (Decimal("1") - a) * smoothed[-1])
    return _envelope(
        forecast_next,
        f"S_t = {a} × X_t + (1 - {a}) × S_{{t-1}}, forecast for next period",
        {"values": [str(n) for n in nums], "alpha": str(a)},
        smoothed_series=[str(s) for s in smoothed],
        forecast_next=str(forecast_next),
    )


def decimal_z_score(value: str, mean: str, std_dev: str) -> dict:
    """Z-score = (value - mean) / std_dev. Used for anomaly detection."""
    v = _to_decimal(value)
    m = _to_decimal(mean)
    sd = _to_decimal(std_dev)
    if sd == 0:
        raise ValueError("Standard deviation cannot be zero")
    z = _quantize((v - m) / sd, 4)
    abs_z = abs(z)
    if abs_z > Decimal("3"):
        severity = "extreme_outlier"
    elif abs_z > Decimal("2"):
        severity = "outlier"
    elif abs_z > Decimal("1"):
        severity = "moderate"
    else:
        severity = "normal"
    return _envelope(
        z,
        f"({v} - {m}) / {sd}",
        {"value": str(v), "mean": str(m), "std_dev": str(sd)},
        severity=severity,
        is_outlier="True" if abs_z > Decimal("2") else "False",
    )


def decimal_percentile(values: list[str], percentile: str) -> dict:
    """Compute the Nth percentile of a list of values (linear interpolation)."""
    nums = sorted([_to_decimal(v) for v in values])
    p = _to_decimal(percentile)
    if not (Decimal("0") <= p <= Decimal("100")):
        raise ValueError("Percentile must be between 0 and 100")
    if not nums:
        raise ValueError("Values list cannot be empty")
    if len(nums) == 1:
        return _envelope(nums[0], f"{p}th percentile of single value", {"values": [str(nums[0])], "percentile": str(p)})
    # Linear interpolation
    rank = (p / Decimal("100")) * Decimal(len(nums) - 1)
    lower_idx = int(rank)
    upper_idx = min(lower_idx + 1, len(nums) - 1)
    fraction = rank - Decimal(lower_idx)
    result = nums[lower_idx] + (nums[upper_idx] - nums[lower_idx]) * fraction
    return _envelope(
        _quantize(result),
        f"{p}th percentile of {len(nums)} sorted values (linear interpolation)",
        {"values": [str(n) for n in nums], "percentile": str(p)},
    )


def decimal_correlation(series_a: list[str], series_b: list[str]) -> dict:
    """Pearson correlation coefficient between two series."""
    a = [_to_decimal(v) for v in series_a]
    b = [_to_decimal(v) for v in series_b]
    if len(a) != len(b):
        raise ValueError("Series must have same length")
    if len(a) < 2:
        raise ValueError("Need at least 2 data points")
    n = Decimal(len(a))
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    var_a = sum((x - mean_a) ** 2 for x in a)
    var_b = sum((y - mean_b) ** 2 for y in b)
    denom = var_a * var_b
    if denom == 0:
        raise ValueError("One or both series have zero variance")
    # sqrt via float fallback (Decimal has no native sqrt that works for this size)
    import math
    r = float(cov) / math.sqrt(float(denom))
    result = _quantize(Decimal(str(r)), 4)
    if abs(result) > Decimal("0.7"):
        strength = "strong"
    elif abs(result) > Decimal("0.4"):
        strength = "moderate"
    elif abs(result) > Decimal("0.2"):
        strength = "weak"
    else:
        strength = "negligible"
    return _envelope(
        result,
        f"Pearson r between {len(a)}-point series",
        {"series_a": [str(x) for x in a], "series_b": [str(x) for x in b]},
        strength=strength,
        direction="positive" if result > 0 else "negative" if result < 0 else "none",
    )


# ---------------------------------------------------------------------------
# Variance decomposition
# ---------------------------------------------------------------------------

def decimal_volume_price_mix(
    actual_volume: str, actual_price: str,
    budget_volume: str, budget_price: str,
) -> dict:
    """Decompose revenue variance into volume effect, price effect, and mix.
    Volume effect = (Actual Vol - Budget Vol) × Budget Price
    Price effect = (Actual Price - Budget Price) × Actual Volume
    Total variance = Volume + Price
    """
    av = _to_decimal(actual_volume)
    ap = _to_decimal(actual_price)
    bv = _to_decimal(budget_volume)
    bp = _to_decimal(budget_price)
    actual_revenue = av * ap
    budget_revenue = bv * bp
    total_variance = actual_revenue - budget_revenue
    volume_effect = _quantize((av - bv) * bp)
    price_effect = _quantize((ap - bp) * av)
    return _envelope(
        _quantize(total_variance),
        "vol_effect + price_effect",
        {
            "actual_volume": str(av), "actual_price": str(ap),
            "budget_volume": str(bv), "budget_price": str(bp),
        },
        actual_revenue=str(_quantize(actual_revenue)),
        budget_revenue=str(_quantize(budget_revenue)),
        volume_effect=str(volume_effect),
        price_effect=str(price_effect),
        volume_pct=str(_quantize(volume_effect / total_variance * Decimal("100"), 1)) if total_variance != 0 else "0",
        price_pct=str(_quantize(price_effect / total_variance * Decimal("100"), 1)) if total_variance != 0 else "0",
    )


# ---------------------------------------------------------------------------
# Risk & VaR
# ---------------------------------------------------------------------------

def decimal_value_at_risk(portfolio_value: str, volatility: str, confidence: str = "0.95", days: int = 1) -> dict:
    """Parametric Value at Risk: VaR = portfolio × volatility × z × sqrt(days).
    confidence: 0.95 (z=1.645) or 0.99 (z=2.326)
    """
    pv = _to_decimal(portfolio_value)
    vol = _to_decimal(volatility)
    conf = _to_decimal(confidence)
    z_lookup = {"0.90": Decimal("1.282"), "0.95": Decimal("1.645"), "0.99": Decimal("2.326")}
    z = z_lookup.get(str(_quantize(conf, 2)), Decimal("1.645"))
    import math
    sqrt_days = Decimal(str(math.sqrt(days)))
    var = _quantize(pv * vol * z * sqrt_days)
    return _envelope(
        var,
        f"{pv} × {vol} × {z} × sqrt({days})",
        {
            "portfolio_value": str(pv), "volatility": str(vol),
            "confidence": str(conf), "days": days,
        },
        z_score=str(z),
        confidence_pct=str(_quantize(conf * Decimal("100"), 1)),
        time_horizon_days=days,
    )


# ---------------------------------------------------------------------------
# Loan & amortisation
# ---------------------------------------------------------------------------

def decimal_loan_payment(principal: str, annual_rate: str, periods: int) -> dict:
    """Standard loan payment (PMT): P × r / (1 - (1+r)^-n).
    annual_rate is decimal (0.05 = 5% APR), periods in months.
    """
    p = _to_decimal(principal)
    annual = _to_decimal(annual_rate)
    if periods <= 0:
        raise ValueError("Periods must be positive")
    monthly_rate = annual / Decimal("12")
    if monthly_rate == 0:
        payment = p / Decimal(periods)
    else:
        # PMT = P × r / (1 - (1+r)^-n)
        factor_float = float(Decimal("1") + monthly_rate) ** (-periods)
        denom = Decimal("1") - Decimal(str(factor_float))
        payment = p * monthly_rate / denom
    payment_q = _quantize(payment, 2)
    total_paid = _quantize(payment_q * Decimal(periods))
    total_interest = _quantize(total_paid - p)
    return _envelope(
        payment_q,
        f"{p} × {monthly_rate} / (1 - (1 + {monthly_rate})^-{periods})",
        {"principal": str(p), "annual_rate": str(annual), "periods": periods},
        total_paid=str(total_paid),
        total_interest=str(total_interest),
        monthly_rate=str(_quantize(monthly_rate, 6)),
        unit="$/period",
    )
