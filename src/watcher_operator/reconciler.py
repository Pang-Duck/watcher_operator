from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from watcher_operator import k8s
from watcher_operator.affinity import merge_required_node_affinity
from watcher_operator.detector import workload_uses_managed_storage
from watcher_operator.policy import StoragePolicy


@dataclass(frozen=True)
class ReconcileResult:
    changed: bool
    managed: bool
    reason: str
    workload: dict[str, Any]


def reconcile_workload(
    workload: dict[str, Any],
    pvcs_by_name: dict[str, dict[str, Any]],
    policy: StoragePolicy,
) -> ReconcileResult:
    patched = k8s.copy_object(workload)
    if not workload_uses_managed_storage(workload, pvcs_by_name, policy):
        return ReconcileResult(
            changed=False,
            managed=False,
            reason="workload does not use managed storage",
            workload=patched,
        )

    template = k8s.ensure_pod_template(patched)
    pod_spec = template.setdefault("spec", {})
    merged_pod_spec, affinity_changed = merge_required_node_affinity(
        pod_spec,
        policy.scheduling_requirements(),
    )
    template["spec"] = merged_pod_spec

    metadata = patched.setdefault("metadata", {})
    annotations = metadata.setdefault("annotations", {})
    annotation_changed = annotations.get(policy.managed_annotation) != "true"
    annotations[policy.managed_annotation] = "true"

    changed = affinity_changed or annotation_changed
    return ReconcileResult(
        changed=changed,
        managed=True,
        reason="managed storage affinity reconciled" if changed else "already reconciled",
        workload=patched,
    )
