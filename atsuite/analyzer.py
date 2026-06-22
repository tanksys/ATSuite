from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Optional

from atsuite.analysis.api import AnalyzeOptions, analyze_recorder
from atsuite.analysis.export import print_summary
from atsuite.analysis.model import AnalysisReport
from atsuite.analysis.observer import RunRecorder
from atsuite.utils import resolve_benchmark_root


def _default_observability(provider: str) -> str:
    key = str(provider or "").strip().lower()
    if key in {"ali", "ali_fc", "ali_agentrun"}:
        return "ali_sls"
    if key in {"aws", "aws_lambda"}:
        return "aws_lambda_cloudwatch"
    if key == "aws_agentcore":
        return "aws_agentcore_cloudwatch"
    if key in {"gcp", "gcp_faas", "gcp_mcp"}:
        return "gcp_cloud_logging"
    if key == "mcp_gateway":
        return "mcp_gateway"
    return "none"


class Analyzer:
    """Analyzer v2 facade.

    The facade owns orchestration only. Runtime events are recorded in
    `RunRecorder`; provider-specific work lives in collectors; pricing is handled
    by pricing policies; report materialization is handled by exporters.
    """

    def __init__(
        self,
        config_path: str | Path,
        provider: str,
        *,
        observability_provider: str = "",
        family: str = "",
        bench_name: str = "",
        trace_name: str = "",
        targets: Optional[Dict[str, Dict[str, Any]]] = None,
        endpoint_map: Optional[Dict[str, Any]] = None,
        output_dir: str | Path = "results",
    ):
        self.config_path = Path(config_path)
        self.provider = provider
        self.observability_provider = observability_provider or _default_observability(provider)
        self.family = family
        try:
            bench_root = resolve_benchmark_root(self.config_path)
            default_bench = bench_root.name
        except Exception:
            default_bench = self.config_path.parent.name
        self.bench_name = bench_name or default_bench
        self.trace_name = trace_name
        self.output_dir = Path(output_dir)
        self.recorder = RunRecorder(
            provider=provider,
            observability_provider=self.observability_provider,
            benchmark=self.bench_name,
            trace=trace_name,
            family=family,
            config_path=str(self.config_path),
            targets=targets or {},
            endpoint_map=endpoint_map or {},
        )
        self.report: Optional[AnalysisReport] = None
        self.events_path = ""
        self._timestamp = ""

    def start(self, uid: str = "", start_time: Optional[float] = None) -> None:
        self.report = None
        self.events_path = ""
        self.recorder.start_run(uid, start_time=start_time)

    def start_node(
        self,
        node_id: int,
        node_name: str,
        node_type: str,
        runtime_name: str = "",
        runtime_config: Optional[Dict[str, Any]] = None,
        *,
        target_id: str = "",
        family: str = "",
        start_time: Optional[float] = None,
    ) -> None:
        self.recorder.start_node(
            node_id=node_id,
            node_name=node_name,
            node_type=node_type,
            runtime_name=runtime_name,
            target_id=target_id,
            family=family,
            runtime_config=runtime_config or {},
            start_time=start_time,
        )

    def end_node(self, node_id: int, *args, end_time: Optional[float] = None, **kwargs) -> None:
        self.recorder.finish_node(node_id, end_time=end_time)

    def record_session_open(
        self,
        *,
        target_id: str,
        runtime_name: str,
        provider_session_id: str = "",
        initialize_request_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        opened_at: Optional[float] = None,
    ) -> None:
        self.recorder.record_session_open(
            target_id=target_id,
            runtime_name=runtime_name,
            provider_session_id=provider_session_id,
            initialize_request_id=initialize_request_id,
            metadata=metadata or {},
            opened_at=opened_at,
        )

    def record_invocation(
        self,
        *,
        node_id: int,
        node_name: str,
        target_id: str,
        runtime_name: str,
        family: str,
        tool_name: str,
        call_id: str,
        status: str,
        provider_request_id: str = "",
        provider_session_id: str = "",
        client_start_time: float = 0.0,
        client_elapsed_ms: float = 0.0,
        error: str = "",
        provider_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.recorder.record_invocation(
            node_id=node_id,
            node_name=node_name,
            target_id=target_id,
            runtime_name=runtime_name,
            family=family,
            tool_name=tool_name,
            call_id=call_id,
            status=status,
            provider_request_id=provider_request_id,
            provider_session_id=provider_session_id,
            client_start_time=client_start_time,
            client_elapsed_ms=client_elapsed_ms,
            error=error,
            provider_metadata=provider_metadata or {},
        )

    def record_state_cleanup(
        self,
        *,
        provider: str,
        services: Iterable[str],
        size_gb: float,
        operation_count: int,
        started_at: float,
        ended_at: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.recorder.record_state(
            provider=provider,
            operation="cleanup",
            services=services,
            size_gb=size_gb,
            operation_count=operation_count,
            started_at=started_at,
            ended_at=ended_at,
            metadata=metadata or {},
        )

    def end(
        self,
        end_time: Optional[float] = None,
        *,
        wait_for_ingestion: bool = True,
        timestamp: Optional[str] = None,
    ) -> AnalysisReport:
        self.recorder.finish_run(end_time=end_time)
        self._timestamp = timestamp or self._timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
        events_dir = self.output_dir / self.provider / self.bench_name
        self.events_path = self.recorder.save_events(events_dir / f"{self._timestamp}.events.json")
        self.report = analyze_recorder(
            self.recorder,
            options=AnalyzeOptions(
                output_dir=self.output_dir,
                wait_for_ingestion=wait_for_ingestion,
                timestamp=self._timestamp,
            ),
        )
        return self.report

    def print_stats(self) -> None:
        if self.report is not None:
            print_summary(self.report)

    def export_results(
        self,
        bench_name: str = "",
        trace_name: str = "",
        timestamp: str = "",
    ) -> Optional[str]:
        if trace_name:
            self.recorder.context.trace = trace_name
        if bench_name:
            self.recorder.context.benchmark = bench_name
            self.bench_name = bench_name
        if timestamp:
            self._timestamp = timestamp
        if self.report is None:
            self.end(timestamp=self._timestamp or timestamp or None)
        return self.report.report_path if self.report is not None else None

    def get_report(self) -> Optional[AnalysisReport]:
        return self.report

    def get_overall_stats(self):
        summary = self.report.summary if self.report is not None else {}
        return SimpleNamespace(
            total_compute_time_ms=float(summary.get("total_compute_time_ms", 0.0) or 0.0),
            total_initialize_time_ms=float(summary.get("total_initialize_time_ms", 0.0) or 0.0),
            total_idle_time_ms=float(summary.get("total_idle_time_ms", 0.0) or 0.0),
            total_client_e2e_ms=float(summary.get("total_client_e2e_ms", 0.0) or 0.0),
            total_app_e2e_ms=float(summary.get("total_app_e2e_ms", 0.0) or 0.0),
            total_tool_exec_ms=float(summary.get("total_tool_exec_ms", 0.0) or 0.0),
            total_state_sync_overhead_ms=float(summary.get("total_state_sync_overhead_ms", 0.0) or 0.0),
            total_framework_overhead_ms=float(summary.get("total_framework_overhead_ms", 0.0) or 0.0),
            total_client_platform_overhead_ms=float(summary.get("total_platform_time_ms", 0.0) or 0.0),
            total_platform_time_ms=float(summary.get("total_platform_time_ms", 0.0) or 0.0),
            total_network_time_ms=float(summary.get("total_network_time_ms", 0.0) or 0.0),
            total_price=float(summary.get("total_price", 0.0) or 0.0),
            total_cpu_price=float(summary.get("total_cpu_price", 0.0) or 0.0),
            total_memory_price=float(summary.get("total_memory_price", 0.0) or 0.0),
            cold_start_total=int(summary.get("cold_start_total", 0) or 0),
            avg_memory_usage_mb=float(summary.get("avg_memory_usage_mb", 0.0) or 0.0),
        )
