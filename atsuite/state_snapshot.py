from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Set


RESERVED_STATE_SNAPSHOT_ARG = "__atsuite_state_snapshot"


def load_state_snapshot_bundle(path: Path | None) -> Dict[str, Any]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise SystemExit(f"Invalid state snapshot payload in {path}: expected JSON object")
    return payload


def maybe_attach_agentcore_state_snapshot(
    args: Dict[str, Any],
    *,
    provider: str,
    target_name: str,
    uid: str,
    state_snapshot_bundle: Optional[Dict[str, Any]],
    seeded_targets: Set[str],
) -> Dict[str, Any]:
    del uid  # Reserved for future per-uid snapshot routing.
    if provider not in ("aws_agentcore", "ali_agentrun"):
        return args
    if target_name in seeded_targets:
        return args
    if not state_snapshot_bundle:
        return args

    services = state_snapshot_bundle.get("services")
    if not isinstance(services, dict):
        return args

    target_payload = services.get(target_name)
    if not isinstance(target_payload, dict):
        return args
    snapshot = target_payload.get("snapshot")
    if not isinstance(snapshot, dict):
        return args

    seeded_targets.add(target_name)
    updated = dict(args)
    updated[RESERVED_STATE_SNAPSHOT_ARG] = snapshot
    return updated


def seed_lambda_state_snapshot_for_uid(
    *,
    provider: str,
    uid: str,
    state_snapshot_bundle: Optional[Dict[str, Any]],
    bucket: str = "atsuite",
    s3_client: Any = None,
) -> Set[str]:
    if provider != "aws_lambda":
        return set()
    if not state_snapshot_bundle:
        return set()

    services = state_snapshot_bundle.get("services")
    if not isinstance(services, dict) or not services:
        return set()

    client = s3_client
    if client is None:
        import boto3

        region = os.environ.get("AWS_REGION", "us-east-1")
        client = boto3.client("s3", region_name=region)

    seeded_services: Set[str] = set()
    for service_name, payload in services.items():
        if not isinstance(service_name, str) or not service_name.strip():
            continue
        if not isinstance(payload, dict):
            continue
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, dict):
            continue

        key = f"{service_name}/{uid}.json"
        body = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
        client.put_object(Bucket=bucket, Key=key, Body=body)
        seeded_services.add(service_name)

    return seeded_services

def seed_alifc_state_snapshot_for_uid(
    *,
    provider: str,
    uid: str,
    state_snapshot_bundle: Optional[Dict[str, Any]],
    bucket: str = "atsuite11",
    client: Any = None,
) -> Set[str]:
    if provider != "ali_fc":
        return set()
    if not state_snapshot_bundle:
        return set()

    services = state_snapshot_bundle.get("services")
    if not isinstance(services, dict) or not services:
        return set()

    client = client
    if client is None:
        from atsuite.ali.oss import AliOSS

        region = os.environ.get("ALI_REGION", "us-east-1")
        client = AliOSS(bucket, region)

    seeded_services: Set[str] = set()
    for service_name, payload in services.items():
        if not isinstance(service_name, str) or not service_name.strip():
            continue
        if not isinstance(payload, dict):
            continue
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, dict):
            continue

        key = f"{service_name}/{uid}.json"
        body = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
        client.append(key, body)
        seeded_services.add(service_name)

    return seeded_services
