"""Python port of the pure financial math in good-shtick/src/shared/
calculatorMath.js, plus the Israeli property-tax bracket constants
duplicated between good-shtick/src/estates/calculators/PurchaseTaxCalculator.js
and good-shtick/src/money/calculators/IsraelPropertyTaxCalculator.js.

This exists so Ask GUT (backend/askgut/routes/chat.py) can give a real,
computed number in a chat reply instead of describing a calculator in
prose. These are small, standard, closed-form formulas -- not application
logic -- so porting them once is low-risk, but the two sides (this file and
calculatorMath.js) must be kept in sync by hand if a formula or a bracket
ever changes; there's no shared source of truth across languages."""
import math


def monthly_pi(principal, annual_rate_pct, years):
    """Standard fixed-rate mortgage payment (principal + interest only)."""
    n = years * 12
    if n <= 0:
        return 0
    r = annual_rate_pct / 100 / 12
    if r == 0:
        return principal / n
    return (principal * r * (1 + r) ** n) / ((1 + r) ** n - 1)


def remaining_balance(principal, annual_rate_pct, years, years_elapsed):
    n = years * 12
    p = min(years_elapsed * 12, n)
    r = annual_rate_pct / 100 / 12
    if r == 0:
        return max(0, principal * (1 - p / n))
    return principal * ((1 + r) ** n - (1 + r) ** p) / ((1 + r) ** n - 1)


def total_interest(principal, annual_rate_pct, years):
    payment = monthly_pi(principal, annual_rate_pct, years)
    return payment * years * 12 - principal


def future_value(amount, annual_rate_pct, years):
    return amount * (1 + annual_rate_pct / 100) ** years


def present_value(target_amount, annual_rate_pct, years):
    return target_amount / (1 + annual_rate_pct / 100) ** years


def growing_annual_total(monthly_amount, annual_growth_pct, years):
    total = 0
    current = monthly_amount
    for _ in range(years):
        total += current * 12
        current *= 1 + annual_growth_pct / 100
    return total


def tiered_tax(amount, brackets):
    """`brackets`: ascending list of {'upTo': number|None, 'ratePct': number}
    -- the last entry's upTo should be None (open-ended top bracket). Returns
    {'total': ..., 'breakdown': [...]}, mirroring calculatorMath.js's shape."""
    remaining = amount
    last_threshold = 0
    total = 0
    breakdown = []
    for b in brackets:
        up_to = math.inf if b.get('upTo') is None else float(b['upTo'])
        slice_width = max(0, min(remaining, up_to - last_threshold))
        slice_tax = slice_width * (float(b['ratePct']) / 100)
        if slice_width > 0:
            breakdown.append({
                'from': last_threshold, 'to': up_to,
                'ratePct': b['ratePct'], 'taxable': slice_width, 'tax': slice_tax,
            })
        total += slice_tax
        remaining -= slice_width
        last_threshold = up_to
        if remaining <= 0:
            break
    return {'total': total, 'breakdown': breakdown}


def future_value_with_contributions(principal, monthly_contribution, annual_rate_pct, years):
    n = years * 12
    r = annual_rate_pct / 100 / 12
    growth_on_principal = principal * (1 + r) ** n
    if r == 0:
        growth_on_contributions = monthly_contribution * n
    else:
        growth_on_contributions = monthly_contribution * (((1 + r) ** n - 1) / r)
    return growth_on_principal + growth_on_contributions


def months_to_payoff(balance, annual_rate_pct, monthly_payment):
    r = annual_rate_pct / 100 / 12
    if r == 0:
        return balance / monthly_payment if monthly_payment > 0 else math.inf
    if monthly_payment <= balance * r:
        return math.inf
    return -math.log(1 - (r * balance) / monthly_payment) / math.log(1 + r)


def format_money(value, currency='USD'):
    symbol = '₪' if currency == 'ILS' else '$'
    if not math.isfinite(value):
        return f'{symbol}0'
    rounded = round(value)
    sign = '-' if rounded < 0 else ''
    return f'{sign}{symbol}{abs(rounded):,}'


# ── Israeli property tax (Mas Rechisha / Mas Shevach) ──
# Ported from money/calculators/IsraelPropertyTaxCalculator.js. 16.1.2025-
# 15.1.2028 brackets (NIS). Keep in sync by hand with that file (and with
# estates/calculators/PurchaseTaxCalculator.js, which duplicates the same
# sole/additional-dwelling brackets -- see the plan note flagging this as a
# separate cleanup candidate).
SOLE_DWELLING_BRACKETS = [
    {'upTo': 1978745, 'ratePct': 0},
    {'upTo': 2347040, 'ratePct': 3.5},
    {'upTo': 6055070, 'ratePct': 5},
    {'upTo': 20183565, 'ratePct': 8},
    {'upTo': None, 'ratePct': 10},
]
ADDITIONAL_DWELLING_BRACKETS = [
    {'upTo': 6055070, 'ratePct': 8},
    {'upTo': None, 'ratePct': 10},
]
SHEVACH_EXEMPTION_CEILING = 5008000  # 2026, sole qualifying residence
SHEVACH_RATE_PCT = 25


def israel_purchase_tax(property_value, is_additional_dwelling=False):
    """Mas Rechisha -- buying. Returns {'total', 'breakdown'}."""
    brackets = ADDITIONAL_DWELLING_BRACKETS if is_additional_dwelling else SOLE_DWELLING_BRACKETS
    return tiered_tax(max(0, property_value), brackets)


def israel_sale_tax(purchase_price, sale_price, sole_residence=True, owned_months=0):
    """Mas Shevach -- selling. Returns {'gain', 'shevach_tax', 'exempt_portion', 'net_sale_proceeds'}."""
    gain = max(0, sale_price - purchase_price)
    qualifies = sole_residence and owned_months >= 18
    shevach_tax = 0.0
    exempt_portion = gain
    if not qualifies:
        shevach_tax = gain * (SHEVACH_RATE_PCT / 100)
        exempt_portion = 0.0
    elif sale_price > SHEVACH_EXEMPTION_CEILING:
        exempt_portion = gain * (SHEVACH_EXEMPTION_CEILING / sale_price)
        taxable_portion = gain - exempt_portion
        shevach_tax = taxable_portion * (SHEVACH_RATE_PCT / 100)
    return {
        'gain': gain,
        'shevach_tax': shevach_tax,
        'exempt_portion': exempt_portion,
        'net_sale_proceeds': sale_price - shevach_tax,
    }
