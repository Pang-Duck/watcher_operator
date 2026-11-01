from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LabelRequirement:
    key: str
    value: str


@dataclass(frozen=True)
class StoragePolicy:
    """Configuration for v1 storage-aware workload reconciliation."""

    storage_class_name: str = "local-path-ha"
    active_node_label: LabelRequirement = LabelRequirement("storage-ha/role", "active")
    ready_node_label: LabelRequirement | None = LabelRequirement("storage-ha/ready", "true")
    ignore_annotation: str = "storage-ha/ignore"
    managed_annotation: str = "storage-ha/managed"

    def scheduling_requirements(self) -> list[LabelRequirement]:
        requirements = [self.active_node_label]
        if self.ready_node_label is not None:
            requirements.append(self.ready_node_label)
        return requirements
