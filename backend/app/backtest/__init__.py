"""Lazy exports keep model/pipeline imports independent of data providers."""

def __getattr__(name):
    if name == "run_backtest":
        from app.backtest.engine import run_backtest
        return run_backtest
    if name == "run_portfolio_backtest":
        from app.backtest.portfolio import run_portfolio_backtest
        return run_portfolio_backtest
    raise AttributeError(name)

__all__ = ["run_backtest", "run_portfolio_backtest"]
