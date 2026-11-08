"""Turn measured browser and Docker samples into reusable summary and curves."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import re
import statistics


def mib(value):
    match = re.fullmatch(r"([\d.]+)\s*(B|KiB|MiB|GiB)", value.strip())
    if match is None:
        raise ValueError("Unknown Docker memory unit")
    return float(match[1]) * {"B": 2**-20, "KiB": 2**-10, "MiB": 1, "GiB": 1024}[match[2]]


def chart(samples, output):
    width, height = 820, 420
    left, top, bottom, right = 74, 64, 362, 784
    end = max(row["seconds"] for row in samples)
    series = [
        ("API", "api_mib", "#1262ba"),
        ("Web", "web_mib", "#ad3e22"),
        ("Chromium aggregate RSS", "browser_rss_mib", "#168369"),
    ]
    maximum = max(1, max(row[key] for row in samples for _, key, _ in series))
    maximum = (int(maximum / 512) + 1) * 512
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Browser and Docker memory during Atlas capacity and recovery">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:system-ui,sans-serif;fill:#25364b;font-size:12px}</style>',
        '<text x="74" y="30" style="font-size:20px;font-weight:600">Atlas capacity and recovery memory</text>',
        '<text x="18" y="56">MiB</text>',
    ]
    for tick in range(5):
        y = bottom - tick / 4 * (bottom - top)
        elements.append(f'<line x1="{left}" y1="{y}" x2="{right}" y2="{y}" stroke="#dce3eb"/>')
        elements.append(f'<text x="{left - 12}" y="{y + 4}" text-anchor="end">{maximum * tick // 4}</text>')
    for tick in range(6):
        x = left + tick / 5 * (right - left)
        elements.append(f'<text x="{x}" y="{bottom + 24}" text-anchor="middle">{end * tick / 300:.1f}</text>')
    elements.append('<text x="429" y="411" text-anchor="middle">Minutes after load began</text>')
    for index, (label, key, color) in enumerate(series):
        coords = " ".join(
            f"{left + row['seconds'] / max(1, end) * (right - left):.1f},{bottom - row[key] / maximum * (bottom - top):.1f}"
            for row in samples
        )
        elements.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2.5"/>')
        x = left + index * 160
        elements.append(f'<line x1="{x}" y1="50" x2="{x+20}" y2="50" stroke="{color}" stroke-width="2.5"/>')
        elements.append(f'<text x="{x+26}" y="54">{label}</text>')
    output.write_text("\n".join([*elements, "</svg>"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("load_directory", type=Path)
    parser.add_argument("resources", type=Path)
    args = parser.parse_args()
    root = args.load_directory
    result = json.loads((root / "result.json").read_text())
    recovery_file = root / "recovery-result.json"
    recovery = json.loads(recovery_file.read_text()) if recovery_file.exists() else None
    started = datetime.fromisoformat(result["load_started_at"].replace("Z", "+00:00")).timestamp()
    records = []
    for line in args.resources.read_text().splitlines():
        sample = json.loads(line)
        if sample["at"] < started or len(sample["docker"]) != 2:
            continue
        data = {row["Name"].split("-")[-2]: row for row in sample["docker"]}
        records.append({
            "seconds": round(sample["at"] - started, 2),
            "api_mib": round(mib(data["api"]["MemUsage"].split("/")[0]), 2),
            "web_mib": round(mib(data["web"]["MemUsage"].split("/")[0]), 2),
            "api_cpu_percent": float(data["api"]["CPUPerc"].rstrip("%")),
            "web_cpu_percent": float(data["web"]["CPUPerc"].rstrip("%")),
            "browser_rss_mib": round(sum(int(row.split()[2]) for row in sample["browser_processes"]) / 1024, 2),
            "protected_unchanged": sample["protected_unchanged"],
            "no_oom_or_restart": len(sample["state"]) == 2 and all(
                not row["oom"] and row["restarts"] == 0 for row in sample["state"]
            ),
            "healthy": len(sample["state"]) == 2 and all(row["health"] == "healthy" for row in sample["state"]),
        })
    if not records:
        raise ValueError("No resource samples overlap the load")
    max_gap = max((later["seconds"] - earlier["seconds"] for earlier, later in zip(records, records[1:])), default=0)
    recovery_end = recovery.get("finished_at", 0) - started if recovery else 0
    complete_sampling = (
        records[0]["seconds"] <= 25 and max_gap <= 25 and recovery_end >= result["elapsed_seconds"]
        and records[-1]["seconds"] >= recovery_end - 25
    )
    with (root / "resources.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    chart(records, root / "memory.svg")
    active = [row for row in records if row["seconds"] <= result["duration_seconds"]]
    window = min(600, result["duration_seconds"] / 4)
    early = [row for row in active if row["seconds"] <= window]
    late = [row for row in active if row["seconds"] >= result["duration_seconds"] - window]
    recovered = [row for row in records if row["seconds"] > result["elapsed_seconds"] + 60]
    memory_keys = ("api_mib", "web_mib", "browser_rss_mib")
    memory_windows = {
        name: {key: statistics.median(row[key] for row in rows) for key in memory_keys}
        for name, rows in (("early_active", early), ("late_active", late), ("after_close", recovered)) if rows
    }
    rss_after_close_zero = bool(recovered) and all(row["browser_rss_mib"] == 0 for row in recovered)
    heap_by_user = {}
    for sample in result.get("client_heap", []):
        if isinstance(sample.get("bytes"), (int, float)):
            heap_by_user.setdefault(sample["user"], []).append(sample["bytes"])
    heap_trend = {
        user: {"samples": len(values), "early_mib": round(statistics.median(values[:max(1, len(values) // 4)]) / 2**20, 2),
               "late_mib": round(statistics.median(values[-max(1, len(values) // 4):]) / 2**20, 2)}
        for user, values in sorted(heap_by_user.items())
    }
    endpoint_groups = {
        "small_write": r"^/api/ledger$|^/api/v1/compute/runtime/[^/]+/(heartbeat|signal)$",
        "ledger_write": r"^/api/ledger$",
        "result_upload": r"^/api/v1/compute/runs$",
        "private_tick": r"^/api/v1/trading/runs/[^/]+/tick$",
        "proof_verify": r"/verify$",
    }
    write_breakdown = {}
    for name, pattern in endpoint_groups.items():
        values = sorted(request["ms"] for request in result["requests"]
                        if request["method"] != "GET" and re.search(pattern, request["path"]))
        if values:
            write_breakdown[name] = {
                "count": len(values),
                "p95_ms": values[math.ceil(len(values) * .95) - 1],
                "max_ms": values[-1],
            }
    standard_writes_pass = write_breakdown.get("small_write", {}).get("p95_ms", math.inf) <= 1500
    short_slo_pass = (
        result["complete"]
        and standard_writes_pass
        and all(value for key, value in result["checks"].items() if key not in {"full_hour", "write_p95"})
    )
    summary = {
        "run_id": result.get("run_id"),
        "images": result.get("images"),
        "source_fingerprint": result.get("source_fingerprint"),
        "contexts": result["actual_contexts"],
        "target_seconds": result["duration_seconds"],
        "elapsed_seconds": result["elapsed_seconds"],
        "workloads": {
            group: sum(row["group"] == group for row in result["groups"])
            for group in sorted({row["group"] for row in result["groups"]})
        },
        "operations": len(result["operations"]),
        "observed_responses": len(result["observed_responses"]),
        "slo": result["slo"],
        "write_breakdown": write_breakdown,
        "checks": result["checks"],
        "errors": result["errors"],
        "resource_samples": len(records),
        "memory_windows_mib": memory_windows,
        "client_heap_trend": heap_trend,
        "resource_sampling_complete": complete_sampling,
        "browser_rss_after_close_zero": rss_after_close_zero,
        "resource_peaks": {
            key: max(row[key] for row in records)
            for key in ("api_mib", "web_mib", "api_cpu_percent", "web_cpu_percent", "browser_rss_mib")
        },
        "browser_rss_active_median_mib": statistics.median(row["browser_rss_mib"] for row in active) if active else None,
        "max_sample_gap_seconds": max_gap,
        "health_ok": all(row["protected_unchanged"] and row["no_oom_or_restart"] and row["healthy"] for row in records),
        "recovery": {key: value for key, value in recovery.items() if key != "samples"} if recovery else None,
        "original_runner_diagnostic_pass": result["diagnostic_pass"],
        "short_slo_pass_with_write_breakdown": short_slo_pass,
        "full_hour_pass": result["success"],
    }
    (root / "capacity-summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
