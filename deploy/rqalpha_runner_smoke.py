import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SOURCE = """from rqalpha.api import order_target_percent, update_universe


def init(context):
    context.placed = False
    update_universe(context.symbols)


def handle_bar(context, bars):
    if not context.placed:
        for symbol in context.symbols:
            order_target_percent(symbol, 0.8 / len(context.symbols))
        context.placed = True
"""


def economic_result(result):
    fields = ("time", "symbol", "side", "quantity", "price", "fee", "commission", "tax")
    return {"equity": result["equity"],
            "trades": [{key: trade[key] for key in fields} for trade in result["trades"]],
            "positions": result["positions"], "corporate_actions": result["corporate_actions"],
            "rejections": result["rejections"]}


def main():
    parser = argparse.ArgumentParser(description="用已配置的固定 RQAlpha/gVisor 复跑真实日线两次")
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", required=True, type=datetime.fromisoformat)
    parser.add_argument("--end", required=True, type=datetime.fromisoformat)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not os.environ.get("ATLAS_DATA_DIR"):
        raise SystemExit("请先配置独立 ATLAS_DATA_DIR，不使用默认个人数据目录")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from app import rqalpha_backtests as rq
    from app.compute_objects import canonical_bytes
    from app.lab_strategies import LabMultiSettings

    zone = ZoneInfo("Asia/Shanghai")
    start = args.start if args.start.tzinfo else args.start.replace(tzinfo=zone)
    end = args.end if args.end.tzinfo else args.end.replace(tzinfo=zone)
    settings = LabMultiSettings(
        engine_id="rqalpha", symbols=args.symbols, interval="1d", start=start, end=end,
        initial_capital=1_000_000, commission_rate=.0008, slippage_rate=0,
        max_position=.95, max_participation_rate=1,
    )
    available, reason = rq.runner_status()
    if not available:
        raise SystemExit(reason or "RQAlpha 隔离执行不可用；不会降级为宿主执行")
    market = rq.resolve(settings)
    runs, fingerprints = [], []
    for index in (1, 2):
        result = rq.execute(SOURCE, settings, market)
        digest = hashlib.sha256(canonical_bytes(economic_result(result))).hexdigest()
        fingerprints.append(digest)
        runs.append({"run": index, "economic_sha256": digest,
                     "equity_points": len(result["equity"]), "trades": len(result["trades"]),
                     "final_equity": result["final_equity"]})
    if fingerprints[0] != fingerprints[1]:
        raise SystemExit("相同冻结输入的两次经济结果不一致")
    report = {"schema": "atlas.rqalpha.runner-smoke/v1", "status": "passed",
              "engine_id": "rqalpha", "engine_version": rq.ENGINE_VERSION,
              "runner_image": rq.runner_image(), "dataset_sha256": market["digest"],
              "source_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
              "window": market["window"], "symbols": settings.symbols,
              "proof_status": "unverified", "runs": runs,
              "same_economic_results": True,
              "excluded_identifiers": ["order_id", "exec_id"],
              "scope": "真实日线原生执行重复性；不是独立资金来源或计算正确性证明。"}
    if args.output:
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            output.write("\n")
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
