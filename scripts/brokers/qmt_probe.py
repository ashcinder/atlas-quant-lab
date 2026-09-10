"""Run on the Windows machine hosting an authorized MiniQMT client; never places orders."""
import json
import os
import platform
import sys
import time


def probe():
    if platform.system() != 'Windows':
        return {'connected': False, 'reason': '需要在安装券商 MiniQMT 的 Windows 主机运行'}
    path = os.getenv('ATLAS_QMT_USERDATA_PATH', '')
    account_id = os.getenv('ATLAS_QMT_ACCOUNT_ID', '')
    if not path or not os.path.isdir(path) or not account_id:
        return {'connected': False, 'reason': '请配置有效的 userdata_mini 路径和账户 ID'}
    try:
        from xtquant.xttrader import XtQuantTrader
        from xtquant.xttype import StockAccount
    except ImportError:
        return {'connected': False, 'reason': '请使用券商支持的 Python 环境安装官方 xtquant'}
    trader = None
    try:
        trader = XtQuantTrader(path, int(time.time()))
        trader.start()
        if trader.connect() != 0:
            return {'connected': False, 'reason': 'MiniQMT 连接失败，请先以极简模式登录客户端'}
        account = StockAccount(account_id)
        if trader.subscribe(account) != 0:
            return {'connected': False, 'reason': '账户订阅失败，请向券商确认账户及接口权限'}
        asset = trader.query_stock_asset(account)
        positions = trader.query_stock_positions(account)
        if asset is None or positions is None:
            return {'connected': False, 'reason': '账户查询未返回有效结果，请核对登录及权限'}
        # Report only success, never balances, positions, account IDs or client paths.
        return {'connected': True, 'asset_query': True, 'positions_query': True,
                'order_enabled': False, 'scope': 'read_only_probe'}
    except Exception:  # noqa: BLE001 - vendor exceptions may contain private account data
        return {'connected': False, 'reason': 'QMT 探测失败，请在本机检查券商客户端与 Python 兼容性'}
    finally:
        if trader is not None:
            try:
                trader.stop()
            except Exception:  # noqa: BLE001, S110 - best-effort SDK cleanup, no private output
                pass


if __name__ == '__main__':
    result = probe()
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result['connected'] else 1)
