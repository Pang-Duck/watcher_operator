from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

K8sObject = dict[str, Any]


def copy_object(obj: Mapping[str, Any]) -> K8sObject:
    return deepcopy(dict(obj))


def annotations(obj: Mapping[str, Any]) -> dict[str, str]:
    metadata = obj.get("metadata") or {}
    return dict(metadata.get("annotations") or {})


def kind(obj: Mapping[str, Any]) -> str:
    return str(obj.get("kind") or "")


def name(obj: Mapping[str, Any]) -> str:
    return str((obj.get("metadata") or {}).get("name") or "")


def namespace(obj: Mapping[str, Any]) -> str:
    return str((obj.get("metadata") or {}).get("namespace") or "default")


def pod_template(obj: Mapping[str, Any]) -> Mapping[str, Any] | None:
    object_kind = kind(obj)
    spec = obj.get("spec") or {}
    if object_kind in {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet"}:
        template = spec.get("template")
        return template if isinstance(template, Mapping) else None
    if object_kind == "Job":
        template = spec.get("template")
        return template if isinstance(template, Mapping) else None
    if object_kind == "CronJob":
        template = (
            (spec.get("jobTemplate") or {})
            .get("spec", {})
            .get("template")
        )
        return template if isinstance(template, Mapping) else None
    return None


def ensure_pod_template(obj: K8sObject) -> K8sObject:
    object_kind = kind(obj)
    spec = obj.setdefault("spec", {})
    if object_kind in {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job"}:
        return spec.setdefault("template", {})
    if object_kind == "CronJob":
        return spec.setdefault("jobTemplate", {}).setdefault("spec", {}).setdefault("template", {})
    raise ValueError(f"unsupported workload kind: {object_kind}")


def volume_claim_names(obj: Mapping[str, Any]) -> set[str]:
    template = pod_template(obj)
    if template is None:
        return set()

    pod_spec = template.get("spec") or {}
    names: set[str] = set()
    for volume in pod_spec.get("volumes") or []:
        claim = (volume or {}).get("persistentVolumeClaim") or {}
        claim_name = claim.get("claimName")
        if claim_name:
            names.add(str(claim_name))
    return names


def volume_claim_template_names(obj: Mapping[str, Any]) -> set[str]:
    if kind(obj) != "StatefulSet":
        return set()
    names: set[str] = set()
    for template in (obj.get("spec") or {}).get("volumeClaimTemplates") or []:
        template_name = ((template or {}).get("metadata") or {}).get("name")
        if template_name:
            names.add(str(template_name))
    return names
