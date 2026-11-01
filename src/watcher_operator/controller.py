from __future__ import annotations

import logging
import os
from typing import Any

import kopf
from kubernetes import client, config
from kubernetes.client import ApiException

from watcher_operator import k8s
from watcher_operator.policy import StoragePolicy
from watcher_operator.reconciler import reconcile_workload

LOG = logging.getLogger("watcher_operator")
POLICY: StoragePolicy | None = None
APPS: client.AppsV1Api | None = None
CORE: client.CoreV1Api | None = None
OPERATOR_NAMESPACE = os.getenv("POD_NAMESPACE", "storage-operator-system")


@kopf.on.startup()
def startup(settings: kopf.OperatorSettings, **_: Any) -> None:
    global POLICY, APPS, CORE
    POLICY = StoragePolicy.from_env()
    settings.peering.name = os.getenv("KOPF_PEERING_NAME", "watcher-operator")
    settings.peering.namespace = OPERATOR_NAMESPACE
    settings.peering.mandatory = True
    settings.persistence.finalizer = os.getenv("KOPF_FINALIZER", "storage-ha.example.com/finalizer")
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    APPS = client.AppsV1Api()
    CORE = client.CoreV1Api()
    LOG.info("Operator initialized for StorageClass %s", POLICY.storage_class_name)


def _reconcile(kind: str, namespace: str, name: str) -> dict[str, Any]:
    if POLICY is None or APPS is None or CORE is None:
        raise RuntimeError("operator has not completed startup")
    if namespace == OPERATOR_NAMESPACE:
        return {"managed": False, "reason": "operator namespace excluded"}
    read_method, patch_method = _workload_methods(kind)
    workload = read_method(name=name, namespace=namespace)
    workload_dict = client.ApiClient().sanitize_for_serialization(workload)
    pvcs: dict[str, dict[str, Any]] = {}
    for claim_name in k8s.volume_claim_names(workload_dict):
        try:
            pvc = CORE.read_namespaced_persistent_volume_claim(name=claim_name, namespace=namespace)
        except ApiException as error:
            if error.status == 404:
                continue
            raise
        pvcs[claim_name] = client.ApiClient().sanitize_for_serialization(pvc)
    result = reconcile_workload(workload_dict, pvcs, POLICY)
    if result.changed:
        patch_method(name=name, namespace=namespace, body=result.workload)
        LOG.info("Patched %s %s/%s", kind, namespace, name)
    return {"managed": result.managed, "changed": result.changed, "reason": result.reason}


def _workload_methods(kind: str):
    if APPS is None:
        raise RuntimeError("Kubernetes clients are not initialized")
    if kind == "Deployment":
        return APPS.read_namespaced_deployment, APPS.patch_namespaced_deployment
    if kind == "StatefulSet":
        return APPS.read_namespaced_stateful_set, APPS.patch_namespaced_stateful_set
    raise ValueError(f"unsupported workload kind: {kind}")


@kopf.on.create("apps", "v1", "deployments")
@kopf.on.update("apps", "v1", "deployments")
def deployment_handler(namespace: str, name: str, **_: Any) -> dict[str, Any]:
    return _reconcile("Deployment", namespace, name)


@kopf.on.create("apps", "v1", "statefulsets")
@kopf.on.update("apps", "v1", "statefulsets")
def statefulset_handler(namespace: str, name: str, **_: Any) -> dict[str, Any]:
    return _reconcile("StatefulSet", namespace, name)


@kopf.on.create("", "v1", "persistentvolumeclaims")
@kopf.on.update("", "v1", "persistentvolumeclaims")
def pvc_handler(namespace: str, name: str, **_: Any) -> None:
    if APPS is None or POLICY is None or namespace == OPERATOR_NAMESPACE:
        return
    for statefulset in APPS.list_namespaced_stateful_set(namespace).items:
        templates = statefulset.spec.volume_claim_templates or []
        if any(
            template.metadata.name
            and name.startswith(f"{template.metadata.name}-{statefulset.metadata.name}-")
            for template in templates
        ):
            _reconcile("StatefulSet", namespace, statefulset.metadata.name)


@kopf.on.probe(id="healthz")
def health_probe(**_: Any) -> dict[str, str]:
    if POLICY is None or APPS is None or CORE is None:
        raise kopf.ProbeError("operator is not initialized")
    return {"status": "ok"}
