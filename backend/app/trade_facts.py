"""Independent facts for platform orders without a strategy cost basis."""


def ensure_manual_fills(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS platform_manual_fills (
        id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, order_id TEXT NOT NULL,
        account_id TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL,
        quantity TEXT NOT NULL, price TEXT NOT NULL, fee TEXT NOT NULL,
        fee_currency TEXT NOT NULL, environment TEXT NOT NULL, executed_at TEXT NOT NULL,
        external_trade_id TEXT NOT NULL,
        UNIQUE(owner_id,account_id,environment,symbol,external_trade_id)
    )""")
