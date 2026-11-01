from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from watcher_operator.policy import LabelRequirement


def required_node_affinity_terms(requirements: list[LabelRequirement]) -> list[dict[str, Any]]:
    return [
        {
            "matchExpressions": [
                {
                    "key": requirement.key,
                    "operator": "In",
                    "values": [requirement.value],
                }
                for requirement in requirements
            ]
        }
    ]


def merge_required_node_affinity(
    pod_spec: Mapping[str, Any],
    requirements: list[LabelRequirement],
) -> tuple[dict[str, Any], bool]:
    """Return a pod spec with required node affinity requirements merged in.

    The merge is intentionally conservative: each existing nodeSelectorTerm gets
    the required expressions appended. Multiple Kubernetes nodeSelectorTerms are
    ORed, while expressions inside one term are ANDed. Appending the new
    expressions to every existing term preserves the user's OR shape and also
    enforces this policy.
    """

    patched = deepcopy(dict(pod_spec))
    affinity = patched.setdefault("affinity", {})
    node_affinity = affinity.setdefault("nodeAffinity", {})
    required = node_affinity.setdefault("requiredDuringSchedulingIgnoredDuringExecution", {})
    terms = required.setdefault("nodeSelectorTerms", [])
    if not terms:
        terms.append({"matchExpressions": []})

    changed = False
    required_expressions = [
        {
            "key": requirement.key,
            "operator": "In",
            "values": [requirement.value],
        }
        for requirement in requirements
    ]

    for term in terms:
        expressions = term.setdefault("matchExpressions", [])
        for expression in required_expressions:
            if not _has_equivalent_expression(expressions, expression):
                expressions.append(deepcopy(expression))
                changed = True

    return patched, changed


def _has_equivalent_expression(
    expressions: list[Mapping[str, Any]],
    wanted: Mapping[str, Any],
) -> bool:
    wanted_values = sorted(str(value) for value in wanted.get("values") or [])
    for expression in expressions:
        if expression.get("key") != wanted.get("key"):
            continue
        if expression.get("operator") != wanted.get("operator"):
            continue
        expression_values = sorted(str(value) for value in expression.get("values") or [])
        if expression_values == wanted_values:
            return True
    return False
