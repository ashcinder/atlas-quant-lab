#!/usr/bin/env python3
"""Full guest boundary fixtures: successful u32/u64/i128 SMA divisions."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import run as runner


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--driver", type=Path, required=True)
    parser.add_argument("--guest", type=Path, required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--signed", action="store_true", help="also test exact negative i32/i64 and narrow MIN/-1")
    args = parser.parse_args()
    results = []
    fixtures = [("u32", 2**32-1, 1, None), ("u64", 2**32, 1, None), ("i128", 10**18, 20, None)]
    if args.signed:
        fixtures += [("signed_i32", 100_000_000, 1, (-7, 3)),
                     ("signed_i64", 100_000_000, 1, (-4_294_967_303, 3)),
                     ("signed_i32_overflow", 100_000_000, 1, (-2**31, -1))]
    for label, price, window, division in fixtures:
        count = max(3, window + 1)
        data = runner.witness(count, "zero")
        data["strategy"]["program"] = [{"sma": window}, {"const": 9501}, "mod"]
        if division is not None:
            numerator, denominator = division
            quotient = (abs(numerator) // abs(denominator)) * (-1 if (numerator < 0) != (denominator < 0) else 1)
            data["strategy"]["program"] = [{"const": numerator}, {"const": denominator}, "div",
                {"const": quotient}, "eq", {"const": 5000}, {"const": 0}, "select"]
        for bar in data["market"]["bars"]:
            for field in ("open_micros", "close_micros", "high_micros", "low_micros"):
                bar[field] = price
        sample = SimpleNamespace(binary=args.driver.resolve(), mode="analyze", program="sma", po2=18,
            disk_segments=True, integrated=False, cpus=3, threads=3, memory="5g", platform="linux/arm64",
            timeout=120, image="atlas-proofbench-api:20261104-arm64",
            health="http://127.0.0.1:18095/api/v1/health",
            experimental_guest=args.guest.resolve(), experimental_image_id=args.image_id)
        folder = args.output.resolve() / label
        if not runner.run(sample, count, folder, witness_data=data):
            raise SystemExit("boundary execution failed; stop")
        result = json.loads((folder / "stdout.json").read_text())
        assert result["execution_only"] is True and "valid" not in result
        results.append(dict(path=label, bars=count, sma_sum=price*window,
                            division_operands=division,
                            complete_journal_matches_canonical=True, stats=result["stats"]))
    (args.output / "summary.json").write_text(json.dumps(results, indent=2))
