import argparse
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from atsuite.con_invoker import run_trace
from atsuite.utils import _cleanup_scaling_configs, _create_scaling_configs
from atsuite.pipeline import resolve_benchmark, CliOverrides
from atsuite.state_snapshot import load_state_snapshot_bundle
from atsuite.uid_strategy import build_request_uid


RESULT_COLUMNS = [
    "index",
    "uid",
    "e2e_time_ms",
    "compute_time_ms",
    "response_time_ms",
    "idle_time_ms",
    "total_price",
    "precise_price",
    "total_cpu_price",
    "total_memory_price",
    "cold_starts",
    "avg_memory_mb",
    "vcpu_hours",
    "memory_gb_hours",
]


def build_unified_result_path(result_dir: Path, provider: str, timestamp: str | None = None) -> Path:
    ts = timestamp or time.strftime("%Y%m%d_%H%M%S")
    return result_dir / f"result_{provider}_{ts}.xlsx"


def save_unified_results(
    result_dir: Path,
    provider: str,
    results: List[Dict],
    timestamp: str | None = None,
) -> Path:
    result_dir.mkdir(exist_ok=True)
    if results:
        df = pd.DataFrame(results)
    else:
        df = pd.DataFrame(columns=RESULT_COLUMNS)
    for column in RESULT_COLUMNS:
        if column not in df.columns:
            df[column] = 0
    df = df[RESULT_COLUMNS]
    
    p99_row = {"index": "p99", "uid": ""}
    for col in RESULT_COLUMNS:
        if col in ("index", "uid"):
            continue
        values = [r.get(col, 0) for r in results if isinstance(r.get(col, 0), (int, float))]
        if values:
            sorted_vals = sorted(values)
            p99_row[col] = sorted_vals[int(len(sorted_vals) * 0.99)]
        else:
            p99_row[col] = 0
    
    df = pd.concat([df, pd.DataFrame([p99_row])], ignore_index=True)
    
    output_path = build_unified_result_path(result_dir, provider, timestamp=timestamp)
    df.to_excel(output_path, index=False, sheet_name="results")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Concurrently invoke run_trace to simulate multiple users.")
    parser.add_argument("--config", required=True, help="Path to benchmark config JSON.")
    parser.add_argument("--url-map", required=True, help="Path to JSON mapping node name to URL.")
    parser.add_argument(
        "--provider",
        required=True,
        choices=["ali_fc", "aws_lambda", "gcp_faas", "ali_agentrun", "aws_agentcore", "gcp_mcp", "mcp_gateway"],
        help="Provider name",
    )
    parser.add_argument("--concurrency", type=int, default=1, help="Number of concurrent requests (default: 1).")
    parser.add_argument("--uid-prefix", default="user", help="Prefix for user IDs (default: 'user'). UIDs will be {prefix}_{index}.")
    parser.add_argument(
        "--uid-mode",
        default="random",
        choices=["random", "index", "fixed"],
        help="UID generation mode: random={prefix}_{i}_{uuid8}, index={prefix}_{i}, fixed={uid-fixed}.",
    )
    parser.add_argument(
        "--uid-fixed",
        default=None,
        help="Exact UID used when --uid-mode fixed.",
    )
    parser.add_argument("--skip-sleep", action="store_true", default=False, help="Skip sleep between nodes.")
    parser.add_argument("--max-workers", type=int, default=None, help="Maximum number of concurrent ready nodes to execute.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility (default: 42).")
    parser.add_argument("--llm-time-mean", type=float, default=1.0, help="Mean of normal distribution for LLM time scale (default: 1.0).")
    parser.add_argument("--llm-time-std", type=float, default=0.2, help="Standard deviation of normal distribution for LLM time scale (default: 0.2).")
    parser.add_argument("--enable-analyzer", action="store_true", default=False, help="Enable analyzer to get real compute time from cloud logs (slower but more accurate).")
    parser.add_argument(
        "--state-snapshot",
        default=None,
        help="Optional path to state snapshot JSON (aws_agentcore injects in-request; aws_lambda pre-seeds S3 per UID).",
    )
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    url_map_path = Path(args.url_map).resolve()
    concurrency = args.concurrency
    uid_prefix = args.uid_prefix
    uid_mode = args.uid_mode
    uid_fixed = args.uid_fixed
    provider = args.provider
    state_snapshot_bundle = load_state_snapshot_bundle(Path(args.state_snapshot).resolve()) if args.state_snapshot else None
    if uid_mode == "fixed" and not uid_fixed:
        parser.error("--uid-fixed is required when --uid-mode fixed")

    np.random.seed(args.seed)
    random.seed(args.seed)
    llm_time_scales = np.random.normal(args.llm_time_mean, args.llm_time_std, concurrency)
    llm_time_scales = np.clip(llm_time_scales, 0.1, 3.0)

    resolved = resolve_benchmark(config_path, provider, CliOverrides())
    # if resolved.family == "mcp_serverless":
    #     for target in resolved.targets.values():
    #         _create_scaling_configs(provider, f"{target.name}-mcp", concurrency)
    #     if provider == "ali_agentrun":
    #         print("[concurrent_invoker] Waiting 30s for ali_agentrun...")
    #         time.sleep(30)

    print(f"[concurrent_invoker] Starting {concurrency} concurrent requests...")
    print(f"[concurrent_invoker] Random seed: {args.seed}, LLM time scale: mean={args.llm_time_mean}, std={args.llm_time_std}")
    print(f"[concurrent_invoker] Generated scales: min={llm_time_scales.min():.3f}, max={llm_time_scales.max():.3f}, mean={llm_time_scales.mean():.3f}")
    
    start_time = time.time()
    
    results: list = []
    failed_results: list = []

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {}

        for i in range(concurrency):
            uid = build_request_uid(
                uid_prefix=uid_prefix,
                index=i,
                uid_mode=uid_mode,
                uid_fixed=uid_fixed,
                uuid_hex=uuid.uuid4().hex,
            )
            llm_time_scale = float(llm_time_scales[i])

            future = executor.submit(
                run_trace,
                config_path,
                url_map_path,
                uid,
                provider=provider,
                skip_sleep=args.skip_sleep,
                max_workers=args.max_workers,
                llm_time_scale=llm_time_scale,
                skip_scaling_config=True,
                skip_analyzer=not args.enable_analyzer,
                state_snapshot_bundle=state_snapshot_bundle,
            )

            futures[future] = (uid, llm_time_scale, i)
            print(f"[concurrent_invoker] Submitted request {i+1}/{concurrency}, uid={uid}, llm_time_scale={llm_time_scale:.3f}")

        completed = 0
        for future in as_completed(futures):
            uid, llm_time_scale, idx = futures[future]
            completed += 1
            try:
                result = future.result()
                run_info = result.get("run", {})
                summary = result.get("summary", {})
                results.append({
                    "index": idx + 1,
                    "uid": run_info.get("uid", uid),
                    "e2e_time_ms": summary.get("run_user_e2e_ms", 0),
                    "compute_time_ms": summary.get("total_compute_time_ms", 0),
                    "response_time_ms": summary.get("total_app_e2e_ms", 0),
                    "idle_time_ms": summary.get("total_idle_time_ms", 0),
                    "total_price": summary.get("total_price", 0),
                    "precise_price": summary.get("total_price", 0),
                    "total_cpu_price": summary.get("total_cpu_price", 0),
                    "total_memory_price": summary.get("total_memory_price", 0),
                    "cold_starts": summary.get("cold_start_total", 0),
                    "avg_memory_mb": summary.get("avg_memory_usage_mb", 0),
                    "vcpu_hours": summary.get("vcpu_hours", 0),
                    "memory_gb_hours": summary.get("memory_gb_hours", 0),
                })
                print(
                    f"[concurrent_invoker] Completed {completed}/{concurrency}, "
                    f"uid={uid}, scale={llm_time_scale:.3f}, "
                    f"e2e={summary.get('run_user_e2e_ms', 0):.2f}ms"
                )
            except Exception as e:
                failed_results.append({
                    "index": idx + 1,
                    "uid": uid,
                    "llm_time_scale": llm_time_scale,
                    "error": str(e),
                })
                print(f"[concurrent_invoker] Failed {completed}/{concurrency}, uid={uid}, scale={llm_time_scale:.3f}: {e}")

    elapsed = time.time() - start_time
    print(f"[concurrent_invoker] All {concurrency} requests finished in {elapsed:.2f}s")
    
    con_result_dir = Path("con_result")
    con_result_dir.mkdir(exist_ok=True)
    
    results.sort(key=lambda x: x["index"])
    
    if results:
        xlsx_file = save_unified_results(con_result_dir, provider, results)
        print(f"[concurrent_invoker] Results saved to {xlsx_file}")
        
        e2e_times = [r["e2e_time_ms"] for r in results]
        compute_times = [r["compute_time_ms"] for r in results]
        prices = [r["total_price"] for r in results]
        
        sorted_e2e = sorted(e2e_times)
        p99_e2e = sorted_e2e[int(len(sorted_e2e) * 0.99)] if len(sorted_e2e) > 0 else 0.0
        sorted_prices = sorted(prices)
        p99_price = sorted_prices[int(len(sorted_prices) * 0.99)] if len(sorted_prices) > 0 else 0.0
        print(f"[concurrent_invoker] Aggregated results:")
        print(f"  E2E time: min={min(e2e_times):.2f}ms, max={max(e2e_times):.2f}ms, "
              f"mean={sum(e2e_times)/len(e2e_times):.2f}ms, p99={p99_e2e:.2f}ms")
        if provider.startswith("ali") and compute_times:
            sorted_compute = sorted(compute_times)
            p99_compute = sorted_compute[int(len(sorted_compute) * 0.99)] if len(sorted_compute) > 0 else 0.0
            print(f"  Compute time: min={min(compute_times):.2f}ms, max={max(compute_times):.2f}ms, "
                  f"mean={sum(compute_times)/len(compute_times):.2f}ms, p99={p99_compute:.2f}ms")
        else:
            print(f"  Compute time: min={min(compute_times):.2f}ms, max={max(compute_times):.2f}ms, "
              f"mean={sum(compute_times)/len(compute_times):.2f}ms")
        print(f"  Total price: min={min(prices):.6f}, max={max(prices):.6f}, "
              f"mean={sum(prices)/len(prices):.6f}, p99={p99_price:.6f}, total={sum(prices):.6f}")
        if provider == "ali_agentrun":
            precise_prices = [r.get("precise_price", 0) for r in results]
            sorted_precise = sorted(precise_prices)
            p99_precise = sorted_precise[int(len(sorted_precise) * 0.99)] if len(sorted_precise) > 0 else 0.0
            print(f"  Precise price: min={min(precise_prices):.6f}, max={max(precise_prices):.6f}, "
                  f"mean={sum(precise_prices)/len(precise_prices):.6f}, p99={p99_precise:.6f}, total={sum(precise_prices):.6f}")
        if provider in ("gcp_faas", "gcp_mcp"):
            cpu_prices = [r.get("total_cpu_price", 0) for r in results]
            memory_prices = [r.get("total_memory_price", 0) for r in results]
            print(
                f"  Total CPU price: min={min(cpu_prices):.6f}, "
                f"max={max(cpu_prices):.6f}, total={sum(cpu_prices):.6f}"
            )
            print(
                f"  Total memory price: min={min(memory_prices):.6f}, "
                f"max={max(memory_prices):.6f}, total={sum(memory_prices):.6f}"
            )
    
    if failed_results:
        df_failed = pd.DataFrame(failed_results)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        xlsx_failed = con_result_dir / f"failed_{provider}_{timestamp}.xlsx"
        df_failed.to_excel(xlsx_failed, index=False, sheet_name="failed")
        print(f"[concurrent_invoker] Failed results saved to {xlsx_failed}")

    # if resolved.family == "mcp_serverless":
    #     for target in resolved.targets.values():
    #         _cleanup_scaling_configs(provider, f"{target.name}-mcp")


if __name__ == "__main__":
    main()
