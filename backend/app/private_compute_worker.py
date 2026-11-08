"""Resource limited subprocess entry point; never emits strategy diagnostics."""
import json
import resource
import sys

MAX_BYTES = 16 * 1024 * 1024


def targets(body, frame):
    import pandas as pd
    from app.models import CustomStrategySpec
    from app.python_strategy import generate_python_targets
    from app.strategies.custom import generate_custom_target
    from app.strategies.signals import generate_target_exposure
    from app.strategies.schedule import contribution_schedule

    snapshot = body["snapshot"]
    if body["source_kind"] == "python":
        return generate_python_targets(frame, snapshot["python_program"])
    if body["source_kind"] == "custom":
        spec = CustomStrategySpec.model_validate(snapshot["custom_strategy"])
        return generate_custom_target(frame, spec, spec.target_position)
    if body["strategy_id"] == "scheduled_dca":
        params = snapshot["params"]
        history = body.get("schedule_history") or [int(frame.index[-1].timestamp())]
        anchor = pd.Timestamp(min(history), unit="s", tz="UTC")
        dates = pd.to_datetime(history, unit="s", utc=True).union(frame.index[frame.index >= anchor]).sort_values()
        schedule = contribution_schedule(dates, int(params["every"]), str(params["unit"]), int(params.get("start_delay", 0)))
        target = pd.Series(schedule, index=dates, dtype=float).reindex(frame.index, fill_value=0.0)
        reasons = pd.Series("等待定投", index=frame.index, dtype=object)
        reasons.loc[target > 0] = "固定金额定投"
        return target, reasons
    return generate_target_exposure(frame, body["strategy_id"], snapshot["params"], 1.0)


def main():
    if sys.platform != "linux":
        return 1
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_AS, (1280 * 1024 * 1024, 1280 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES, MAX_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        from datetime import UTC, datetime
        import pandas as pd
        from app.backtest import run_backtest
        from app.data.service import DataBundle
        from app.models import Asset, BacktestRequest

        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return 1
        body = json.loads(raw)
        frame = pd.DataFrame(body["bars"])
        frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
        frame = frame.set_index("time")
        if body.get("operation") == "targets":
            values, reasons = targets(body, frame)
            output = {"targets": [float(value) for value in values], "reasons": [str(reason) for reason in reasons]}
        else:
            request = BacktestRequest.model_validate(body["request"])
            if request.execution_pipeline is not None or request.python_source is not None:
                return 1
            bundle = DataBundle(asset=Asset.model_validate(body["asset"]), frame=frame,
                                source=body["source"], source_note=None, fetched_at=datetime.now(UTC), cache_hit=True)
            output = run_backtest(request, bundle, supplied_program=body.get("program")).model_dump(mode="json")
        encoded = json.dumps(output, allow_nan=False).encode()
        if len(encoded) > MAX_BYTES:
            return 1
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
