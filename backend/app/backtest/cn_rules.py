"""A-share execution primitives for a future shared backtest contract.

This module is not wired into the production engines. Prices and limits must be
unadjusted, point-in-time exchange data; None means unavailable, never 10%.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class OpeningMarket:
    session: date
    price: Decimal
    upper_limit: Decimal | None
    lower_limit: Decimal | None
    suspended: bool
    limits_known: bool


@dataclass(frozen=True)
class Position:
    quantity: int
    sellable: int


@dataclass(frozen=True)
class Decision:
    quantity: int
    reason: str


def executable_quantity(side: Literal['buy', 'sell'], requested: int, symbol: str,
                        position: Position, market: OpeningMarket) -> Decision:
    """Apply T+1 inventory, lot size and conservative price-limit matching.

    A sellable quantity is supplied by the portfolio's T+1 ledger, which must
    incorporate corporate actions. A no-limit session has limits_known=True
    and both limits None; unknown data must set limits_known=False.
    """
    if side not in ('buy', 'sell') or requested <= 0:
        raise ValueError('invalid order')
    if not symbol.endswith(('.SS', '.SZ')):
        raise ValueError('only SSE/SZSE common shares are supported')
    if position.quantity < 0 or not 0 <= position.sellable <= position.quantity:
        raise ValueError('invalid position ledger')
    if market.suspended:
        return Decision(0, 'suspended')
    if not market.limits_known:
        raise ValueError('historical price limits are unavailable')
    if not market.price.is_finite() or market.price <= 0:
        raise ValueError('invalid opening price')
    if (market.upper_limit is None) != (market.lower_limit is None):
        raise ValueError('incomplete historical price limits')
    if market.upper_limit is not None:
        if market.upper_limit <= 0 or market.lower_limit <= 0 or market.lower_limit > market.upper_limit:
            raise ValueError('invalid historical price limits')
        if market.price > market.upper_limit or market.price < market.lower_limit:
            raise ValueError('opening price outside historical limits')
        if side == 'buy' and market.price >= market.upper_limit:
            return Decision(0, 'upper_limit')
        if side == 'sell' and market.price <= market.lower_limit:
            return Decision(0, 'lower_limit')
    star = symbol.startswith('688') and symbol.endswith('.SS')
    if side == 'buy':
        amount = requested if star and requested >= 200 else (0 if star else requested // 100 * 100)
        return Decision(amount, 'ok' if amount else 'below_minimum_lot')
    amount = min(requested, position.sellable)
    if amount == 0:
        return Decision(0, 't_plus_one')
    if star:
        amount = amount if amount >= 200 or amount == position.quantity else 0
    elif amount != position.quantity:
        amount = amount // 100 * 100
    return Decision(amount, 'ok' if amount else 'below_minimum_lot')


def transaction_cost(side: Literal['buy', 'sell'], notional: Decimal, session: date,
                     commission_rate: Decimal, minimum_commission: Decimal = Decimal('5'),
                     transfer_rate: Decimal = Decimal('0.00001')) -> dict[str, Decimal]:
    """Per-order commission, transfer fee and historical stamp duty.

    This model assumes a single complete fill; callers must aggregate partial
    fills by order before applying the commission minimum. Dividend tax and
    exchange-specific historical transfer fees require separate data.
    """
    if side not in ('buy', 'sell') or notional <= 0 or min(commission_rate, minimum_commission, transfer_rate) < 0:
        raise ValueError('invalid cost inputs')
    stamp = Decimal('0') if side == 'buy' else (Decimal('0.001') if session < date(2023, 8, 28) else Decimal('0.0005'))
    commission = max(minimum_commission, notional * commission_rate)
    tax = notional * stamp
    transfer = notional * transfer_rate
    return {'commission': commission, 'stamp_duty': tax, 'transfer': transfer,
            'total': commission + tax + transfer}
