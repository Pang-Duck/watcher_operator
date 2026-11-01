from __future__ import annotations

from dataclasses import dataclass
import os


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

    @classmethod
    def from_env(cls) -> "StoragePolicy":
        ready_key = os.getenv("READY_NODE_LABEL_KEY", "storage-ha/ready")
        ready_value = os.getenv("READY_NODE_LABEL_VALUE", "true")
        return cls(
            storage_class_name=os.getenv("STORAGE_CLASS_NAME", "local-path-ha"),
            active_node_label=LabelRequirement(
                os.getenv("ACTIVE_NODE_LABEL_KEY", "storage-ha/role"),
                os.getenv("ACTIVE_NODE_LABEL_VALUE", "active"),
            ),
            ready_node_label=(
                LabelRequirement(ready_key, ready_value)
                if ready_key.strip()
                else None
            ),
            ignore_annotation=os.getenv("IGNORE_ANNOTATION", "storage-ha/ignore"),
            managed_annotation=os.getenv("MANAGED_ANNOTATION", "storage-ha/managed"),
        )

    def scheduling_requirements(self) -> list[LabelRequirement]:
        requirements = [self.active_node_label]
        if self.ready_node_label is not None:
            requirements.append(self.ready_node_label)
        return requirements
