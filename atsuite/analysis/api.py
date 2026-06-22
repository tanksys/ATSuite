from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from atsuite.analysis.aggregation import ReportAggregator
from atsuite.analysis.collectors import ProviderCollector, create_collector
from atsuite.analysis.export import AnalysisExporter
from atsuite.analysis.model import AnalysisReport
from atsuite.analysis.observer import RunRecorder
from atsuite.analysis.pricing import PricingPolicy, create_pricing_policy


@dataclass
class AnalyzeOptions:
    output_dir: str | Path = "results"
    wait_for_ingestion: bool = False
    timestamp: Optional[str] = None


def analyze_recorder(
    recorder: RunRecorder,
    *,
    options: Optional[AnalyzeOptions] = None,
    collector: Optional[ProviderCollector] = None,
    pricing_policy: Optional[PricingPolicy] = None,
) -> AnalysisReport:
    options = options or AnalyzeOptions()
    context = recorder.context
    collector = collector or create_collector(context.observability_provider)
    if options.wait_for_ingestion:
        wait = getattr(collector, "wait_for_ingestion", None)
        if callable(wait):
            wait(
                context,
                nodes=recorder.nodes,
                invocations=recorder.invocations,
                sessions=recorder.sessions,
            )
        else:
            delay = float(getattr(collector, "default_ingestion_delay_s", 0.0) or 0.0)
            if delay > 0:
                time.sleep(delay)

    collection = collector.collect(
        context,
        nodes=recorder.nodes,
        invocations=recorder.invocations,
        sessions=recorder.sessions,
    )
    pricing_policy = pricing_policy or create_pricing_policy(
        context.provider,
        context.observability_provider,
    )
    costs = pricing_policy.price(
        context,
        metrics=collection.metrics,
        state=recorder.state,
    )
    report = ReportAggregator().aggregate(
        context,
        nodes=recorder.nodes,
        invocations=recorder.invocations,
        metrics=collection.metrics,
        costs=costs,
        diagnostics=collection.diagnostics,
        evidence=collection.evidence,
    )
    return AnalysisExporter(options.output_dir).export(
        report,
        collection.evidence,
        provider=context.provider,
        benchmark=context.benchmark,
        timestamp=options.timestamp,
    )


def analyze_events(
    events_path: str | Path,
    options: Optional[AnalyzeOptions] = None,
    *,
    collector: Optional[ProviderCollector] = None,
    pricing_policy: Optional[PricingPolicy] = None,
) -> AnalysisReport:
    recorder = RunRecorder.from_events(events_path)
    return analyze_recorder(
        recorder,
        options=options,
        collector=collector,
        pricing_policy=pricing_policy,
    )
