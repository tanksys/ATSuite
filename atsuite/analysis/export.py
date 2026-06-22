from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from atsuite.analysis.model import AnalysisReport, EvidenceRecord


class AnalysisExporter:
    def __init__(self, base_dir: str | Path = "results"):
        self.base_dir = Path(base_dir)

    def export(
        self,
        report: AnalysisReport,
        evidence: Iterable[EvidenceRecord],
        *,
        provider: str,
        benchmark: str,
        timestamp: Optional[str] = None,
    ) -> AnalysisReport:
        ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = self.base_dir / provider / benchmark
        output_dir.mkdir(parents=True, exist_ok=True)

        evidence_path = output_dir / f"{ts}.evidence.jsonl"
        with evidence_path.open("w", encoding="utf-8") as handle:
            for record in evidence:
                handle.write(json.dumps(record.to_dict(), ensure_ascii=False, default=str) + "\n")

        report.evidence_path = str(evidence_path)
        report_path = output_dir / f"{ts}.report.json"
        report.report_path = str(report_path)
        report_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        return report


def print_summary(report: AnalysisReport) -> None:
    summary = report.summary
    print("\n" + "=" * 60)
    print("ATSUITE ANALYSIS V2")
    print("=" * 60)
    print(f"Provider: {report.run.get('provider')} ({report.run.get('observability_provider')})")
    print(f"Benchmark: {report.run.get('benchmark')} / {report.run.get('trace')}")
    print(f"Run User E2E: {summary.get('run_user_e2e_ms', 0):.2f}ms")
    print(f"Total Compute: {summary.get('total_compute_time_ms', 0):.2f}ms")
    print(f"Total Initialize: {summary.get('total_initialize_time_ms', 0):.2f}ms")
    print(f"Total Idle: {summary.get('total_idle_time_ms', 0):.2f}ms")
    print(f"Total Client E2E: {summary.get('total_client_e2e_ms', 0):.2f}ms")
    print(f"Total App E2E: {summary.get('total_app_e2e_ms', 0):.2f}ms")
    print(f"Total Tool Exec: {summary.get('total_tool_exec_ms', 0):.2f}ms")
    print(f"Cold Starts: {summary.get('cold_start_total', 0)}")
    print(f"Avg Memory: {summary.get('avg_memory_usage_mb', 0):.2f}MB")
    print(
        f"Total Price: {summary.get('total_price', 0):.10f} "
        f"{summary.get('currency', 'USD')}"
    )
    if report.diagnostics:
        print(f"Diagnostics: {len(report.diagnostics)} issue(s)")
    print(f"Report: {report.report_path}")
    print(f"Evidence: {report.evidence_path}")
    print("=" * 60)
