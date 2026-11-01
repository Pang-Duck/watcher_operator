from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from watcher_operator import k8s
from watcher_operator.policy import StoragePolicy


def is_ignored(obj: Mapping[str, Any], policy: StoragePolicy) -> bool:
    return k8s.annotations(obj).get(policy.ignore_annotation, "").lower() == "true"


def pvc_uses_storage_class(
    pvc: Mapping[str, Any],
    storage_class_name: str,
) -> bool:
    spec = pvc.get("spec") or {}
    return spec.get("storageClassName") == storage_class_name


def workload_uses_managed_storage(
    workload: Mapping[str, Any],
    pvcs_by_name: Mapping[str, Mapping[str, Any]],
    policy: StoragePolicy,
) -> bool:
    if is_ignored(workload, policy):
        return False

    for claim_name in k8s.volume_claim_names(workload):
        pvc = pvcs_by_name.get(claim_name)
        if pvc is not None and pvc_uses_storage_class(pvc, policy.storage_class_name):
            return True

    # StatefulSet volumeClaimTemplates create PVCs with generated names. The
    # template itself carries the StorageClass, so it can be detected before PVCs
    # exist.
    for template in (workload.get("spec") or {}).get("volumeClaimTemplates") or []:
        if pvc_uses_storage_class(template, policy.storage_class_name):
            return True

    return False
