from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Protocol

from atsuite.analysis.model import CostLineItem, ProviderMetric, RunContext, StateObservation


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


class PricingPolicy(Protocol):
    provider: str

    def price(
        self,
        context: RunContext,
        *,
        metrics: List[ProviderMetric],
        state: List[StateObservation],
    ) -> List[CostLineItem]:
        ...


class BasePricingPolicy:
    provider = "none"
    currency = "USD"

    def price(
        self,
        context: RunContext,
        *,
        metrics: List[ProviderMetric],
        state: List[StateObservation],
    ) -> List[CostLineItem]:
        return []


class AliPricingPolicy(BasePricingPolicy):
    provider = "ali"
    currency = "CNY"

    @staticmethod
    def _ali_parts(count: int, cpu: float, memory: float, disk: float, active_time_ms: float, idle_time_ms: float = 0.0, min_instance_time_ms: float = 0.0) -> Dict[str, float]:
        cu = count * 0.0075 + cpu * (active_time_ms / 1000) + (memory / 1024) * ((active_time_ms + idle_time_ms) / 1000) * 0.15
        disk_cu = 0.0
        if disk > 512:
            disk_cu = (disk / 1024) * (min_instance_time_ms / 1000) * 0.05
            cu += disk_cu
        if cu <= 200000000:
            factor = 0.000088
        elif cu >= 1000000000:
            factor = 0.000072
        else:
            factor = 0.000080
        return {
            "request": count * 0.0075 * factor,
            "cpu": cpu * (active_time_ms / 1000) * factor,
            "memory": (memory / 1024) * ((active_time_ms + idle_time_ms) / 1000) * 0.15 * factor,
            "disk": disk_cu * factor,
            "total": cu * factor,
            "factor": factor,
        }

    def price(self, context: RunContext, *, metrics: List[ProviderMetric], state: List[StateObservation]) -> List[CostLineItem]:
        items: List[CostLineItem] = []
        for metric in metrics:
            if metric.provider != "ali":
                continue
            f = metric.fields
            active_ms = _num(f.get("invoker_function_ms"), _num(f.get("duration_ms"), _num(f.get("elapsed_time_ms"))))
            parts = self._ali_parts(
                1,
                _num(f.get("cpu"), 1.0),
                _num(f.get("memory"), 1024.0),
                _num(f.get("disk"), 512.0),
                max(0.0, active_ms),
            )
            for category in ("request", "cpu", "memory", "disk"):
                amount = parts[category]
                if amount <= 0:
                    continue
                items.append(
                    CostLineItem(
                        category=category,
                        provider="ali",
                        amount=amount,
                        currency=self.currency,
                        node_id=metric.node_id,
                        invocation_call_id=metric.invocation_call_id,
                        formula=f"Ali FC {category} from active_ms={active_ms:.3f}",
                    )
                )
        for obs in state:
            if obs.provider not in ("ali", "ali_fc", "ali_agentrun"):
                continue
            duration_s = max(0.0, _num(obs.ended_at) - _num(obs.started_at))
            calls = max(0, int(obs.operation_count or 0))
            amount = 4.63e-8 * obs.size_gb * duration_s + 0.01 * (calls / 10000)
            if amount > 0:
                items.append(
                    CostLineItem(
                        category="storage",
                        provider="ali",
                        amount=amount,
                        currency=self.currency,
                        resource_id="oss",
                        formula=f"OSS {obs.size_gb:.6f}GB * {duration_s:.2f}s + {calls} ops",
                    )
                )
        return items


class AWSLambdaPricingPolicy(BasePricingPolicy):
    provider = "aws_lambda"
    currency = "USD"

    def price(self, context: RunContext, *, metrics: List[ProviderMetric], state: List[StateObservation]) -> List[CostLineItem]:
        items: List[CostLineItem] = []
        for metric in metrics:
            if metric.provider != "aws_lambda":
                continue
            f = metric.fields
            billed_ms = _num(f.get("billed_duration_ms"), _num(f.get("duration_ms"), _num(f.get("elapsed_time_ms"))))
            billed_ms += _num(f.get("init_duration_ms"))
            memory_mb = max(128.0, _num(f.get("memory"), _num(f.get("memory_limit_mb"), 1024.0)))
            disk_mb = _num(f.get("disk"), 512.0)
            request_cost = 0.0000002
            duration_cost = (memory_mb / 1024.0) * (billed_ms / 1000.0) * 0.0000166667
            storage_cost = 0.0
            if disk_mb > 512:
                storage_cost = ((disk_mb - 512.0) / 1024.0) * (billed_ms / 1000.0) * 0.0000000309
            items.extend(
                [
                    CostLineItem("request", "aws_lambda", request_cost, self.currency, node_id=metric.node_id, invocation_call_id=metric.invocation_call_id, formula="Lambda request"),
                    CostLineItem("memory", "aws_lambda", duration_cost, self.currency, node_id=metric.node_id, invocation_call_id=metric.invocation_call_id, formula=f"Lambda {memory_mb}MB * {billed_ms:.3f}ms"),
                ]
            )
            if storage_cost > 0:
                items.append(
                    CostLineItem("storage", "aws_lambda", storage_cost, self.currency, node_id=metric.node_id, invocation_call_id=metric.invocation_call_id, formula=f"Lambda ephemeral storage {disk_mb}MB")
                )
        for obs in state:
            if obs.provider not in ("aws", "aws_lambda", "aws_agentcore"):
                continue
            duration_s = max(0.0, _num(obs.ended_at) - _num(obs.started_at))
            seconds_per_month = 30 * 24 * 3600
            storage_cost = obs.size_gb * 0.023 * (duration_s / seconds_per_month)
            put_get_count = max(0, int(obs.operation_count or 0)) * 2
            api_cost = put_get_count * (0.005 / 1000) + put_get_count * (0.0004 / 1000)
            amount = storage_cost + api_cost
            if amount > 0:
                items.append(
                    CostLineItem(
                        "storage",
                        "aws_lambda",
                        amount,
                        self.currency,
                        resource_id="s3",
                        formula=f"S3 {obs.size_gb:.6f}GB * {duration_s:.2f}s + {put_get_count} ops",
                    )
                )
        return items


class AWSAgentCorePricingPolicy(BasePricingPolicy):
    provider = "aws_agentcore"
    currency = "USD"

    def price(self, context: RunContext, *, metrics: List[ProviderMetric], state: List[StateObservation]) -> List[CostLineItem]:
        items: List[CostLineItem] = []
        for metric in metrics:
            if metric.provider != "aws_agentcore" or metric.source != "agentcore_usage":
                continue
            f = metric.fields
            vcpu_hours = _num(f.get("vcpu_hours"))
            mem_gb_hours = _num(f.get("memory_gb_hours"))
            cpu_cost = vcpu_hours * 0.0895
            memory_cost = mem_gb_hours * 0.00945
            runtime_name = str(f.get("runtime_name") or "")
            if cpu_cost > 0:
                items.append(
                    CostLineItem("cpu", "aws_agentcore", cpu_cost, self.currency, resource_id=runtime_name, formula=f"{vcpu_hours:.10f} vCPU-h * 0.0895")
                )
            if memory_cost > 0:
                items.append(
                    CostLineItem("memory", "aws_agentcore", memory_cost, self.currency, resource_id=runtime_name, formula=f"{mem_gb_hours:.10f} GB-h * 0.00945")
                )
        # AgentCore can still use external state snapshots for some workflows.
        items.extend(AWSLambdaPricingPolicy().price(context, metrics=[], state=state))
        for item in items:
            if item.provider == "aws_lambda":
                item.provider = "aws_agentcore"
        return items


class GCPPricingPolicy(BasePricingPolicy):
    provider = "gcp"
    currency = "USD"

    @staticmethod
    def _parts(cpu: float, memory_mb: float, elapsed_time_ms: float) -> Dict[str, float]:
        duration_sec = math.ceil(max(0.0, elapsed_time_ms) / 100.0) * 0.1
        vcpu_seconds = duration_sec * cpu
        gib_seconds = duration_sec * (memory_mb / 1024.0)
        return {
            "cpu": vcpu_seconds * 0.000024,
            "memory": gib_seconds * 0.0000025,
            "request": 0.40 / 1_000_000,
            "duration_sec": duration_sec,
        }

    def price(self, context: RunContext, *, metrics: List[ProviderMetric], state: List[StateObservation]) -> List[CostLineItem]:
        items: List[CostLineItem] = []
        for metric in metrics:
            if metric.provider != "gcp":
                continue
            f = metric.fields
            elapsed_ms = _num(f.get("elapsed_time_ms"), _num(f.get("duration_ms")))
            cpu = max(0.0, _num(f.get("cpu"), 1.0))
            memory_mb = max(0.0, _num(f.get("memory"), _num(f.get("memory_mb"), 1024.0)))
            parts = self._parts(cpu, memory_mb, elapsed_ms)
            for category in ("cpu", "memory", "request"):
                items.append(
                    CostLineItem(
                        category,
                        "gcp",
                        parts[category],
                        self.currency,
                        node_id=metric.node_id,
                        invocation_call_id=metric.invocation_call_id,
                        formula=f"GCP Cloud Run {category}, billed={parts['duration_sec']:.3f}s",
                    )
                )
        for obs in state:
            if obs.provider not in ("gcp", "gcp_faas", "gcp_mcp"):
                continue
            duration_s = max(0.0, _num(obs.ended_at) - _num(obs.started_at))
            storage_rate_per_gb_sec = 0.020 / (30 * 24 * 3600)
            storage_cost = obs.size_gb * duration_s * storage_rate_per_gb_sec
            op_cost = max(0, int(obs.operation_count or 0)) * (0.005 / 10_000)
            amount = storage_cost + op_cost
            if amount > 0:
                items.append(
                    CostLineItem(
                        "storage",
                        "gcp",
                        amount,
                        self.currency,
                        resource_id="cloud_storage",
                        formula=f"GCS {obs.size_gb:.6f}GB * {duration_s:.2f}s + {obs.operation_count} ops",
                    )
                )
        return items


class GatewayPricingPolicy(BasePricingPolicy):
    provider = "mcp_gateway"
    currency = "USD"


def create_pricing_policy(provider: str, observability_provider: str = "") -> PricingPolicy:
    provider_key = str(provider or "").strip().lower()
    obs_key = str(observability_provider or "").strip().lower()
    if provider_key.startswith("ali") or obs_key.startswith("ali"):
        return AliPricingPolicy()
    if provider_key == "aws_agentcore" or obs_key.startswith("aws_agentcore"):
        return AWSAgentCorePricingPolicy()
    if provider_key.startswith("aws") or obs_key.startswith("aws_lambda"):
        return AWSLambdaPricingPolicy()
    if provider_key.startswith("gcp") or obs_key.startswith("gcp"):
        return GCPPricingPolicy()
    if provider_key == "mcp_gateway" or obs_key == "mcp_gateway":
        return GatewayPricingPolicy()
    return BasePricingPolicy()
