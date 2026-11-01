import os
import unittest
from unittest.mock import patch

from watcher_operator.policy import StoragePolicy


class PolicyTests(unittest.TestCase):
    def test_loads_configmap_values_from_environment(self):
        values = {
            "STORAGE_CLASS_NAME": "fast-local",
            "ACTIVE_NODE_LABEL_KEY": "storage-ha/role",
            "ACTIVE_NODE_LABEL_VALUE": "primary",
            "READY_NODE_LABEL_KEY": "storage-ha/ready",
            "READY_NODE_LABEL_VALUE": "yes",
            "IGNORE_ANNOTATION": "storage-ha/skip",
            "MANAGED_ANNOTATION": "storage-ha/owned",
        }
        with patch.dict(os.environ, values, clear=True):
            policy = StoragePolicy.from_env()

        self.assertEqual(policy.storage_class_name, "fast-local")
        self.assertEqual(policy.active_node_label.key, "storage-ha/role")
        self.assertEqual(policy.active_node_label.value, "primary")
        self.assertEqual(policy.ready_node_label.value, "yes")
        self.assertEqual(policy.ignore_annotation, "storage-ha/skip")
        self.assertEqual(policy.managed_annotation, "storage-ha/owned")

    def test_empty_ready_label_disables_readiness_requirement(self):
        with patch.dict(os.environ, {"READY_NODE_LABEL_KEY": ""}, clear=True):
            policy = StoragePolicy.from_env()

        self.assertIsNone(policy.ready_node_label)
        self.assertEqual(len(policy.scheduling_requirements()), 1)


if __name__ == "__main__":
    unittest.main()
