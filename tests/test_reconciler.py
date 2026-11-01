import unittest

from watcher_operator import StoragePolicy, reconcile_workload


class ReconcilerTests(unittest.TestCase):
    def test_reconciles_deployment_that_uses_managed_pvc(self):
        policy = StoragePolicy(storage_class_name="local-path-ha")
        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "api", "namespace": "app-system"},
            "spec": {
                "template": {
                    "spec": {
                        "volumes": [
                            {"name": "data", "persistentVolumeClaim": {"claimName": "api-data"}}
                        ]
                    }
                }
            },
        }
        pvcs = {"api-data": {"spec": {"storageClassName": "local-path-ha"}}}

        result = reconcile_workload(deployment, pvcs, policy)

        self.assertTrue(result.changed)
        self.assertTrue(result.managed)
        self.assertEqual(
            result.workload["metadata"]["annotations"]["storage-ha/managed"],
            "true",
        )
        expressions = result.workload["spec"]["template"]["spec"]["affinity"]["nodeAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"
        ]["nodeSelectorTerms"][0]["matchExpressions"]
        self.assertIn({"key": "storage-ha/role", "operator": "In", "values": ["active"]}, expressions)
        self.assertIn({"key": "storage-ha/ready", "operator": "In", "values": ["true"]}, expressions)

    def test_skips_deployment_without_managed_pvc(self):
        policy = StoragePolicy(storage_class_name="local-path-ha")
        deployment = {
            "kind": "Deployment",
            "metadata": {"name": "api"},
            "spec": {
                "template": {
                    "spec": {
                        "volumes": [
                            {"name": "cache", "persistentVolumeClaim": {"claimName": "cache"}}
                        ]
                    }
                }
            },
        }
        pvcs = {"cache": {"spec": {"storageClassName": "standard"}}}

        result = reconcile_workload(deployment, pvcs, policy)

        self.assertFalse(result.changed)
        self.assertFalse(result.managed)

    def test_statefulset_volume_claim_template_is_detected_before_pvc_exists(self):
        policy = StoragePolicy(storage_class_name="local-path-ha")
        statefulset = {
            "kind": "StatefulSet",
            "metadata": {"name": "database"},
            "spec": {
                "volumeClaimTemplates": [
                    {
                        "metadata": {"name": "data"},
                        "spec": {"storageClassName": "local-path-ha"},
                    }
                ],
                "template": {"spec": {"containers": [{"name": "db"}]}},
            },
        }

        result = reconcile_workload(statefulset, {}, policy)

        self.assertTrue(result.changed)
        self.assertTrue(result.managed)

    def test_existing_node_affinity_terms_are_preserved_and_restricted(self):
        policy = StoragePolicy(storage_class_name="local-path-ha")
        deployment = {
            "kind": "Deployment",
            "metadata": {"name": "api"},
            "spec": {
                "template": {
                    "spec": {
                        "volumes": [
                            {"name": "data", "persistentVolumeClaim": {"claimName": "api-data"}}
                        ],
                        "affinity": {
                            "nodeAffinity": {
                                "requiredDuringSchedulingIgnoredDuringExecution": {
                                    "nodeSelectorTerms": [
                                        {
                                            "matchExpressions": [
                                                {
                                                    "key": "node.kubernetes.io/instance-type",
                                                    "operator": "In",
                                                    "values": ["storage"],
                                                }
                                            ]
                                        }
                                    ]
                                }
                            }
                        },
                    }
                }
            },
        }
        pvcs = {"api-data": {"spec": {"storageClassName": "local-path-ha"}}}

        result = reconcile_workload(deployment, pvcs, policy)

        expressions = result.workload["spec"]["template"]["spec"]["affinity"]["nodeAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"
        ]["nodeSelectorTerms"][0]["matchExpressions"]
        self.assertIn(
            {
                "key": "node.kubernetes.io/instance-type",
                "operator": "In",
                "values": ["storage"],
            },
            expressions,
        )
        self.assertIn({"key": "storage-ha/role", "operator": "In", "values": ["active"]}, expressions)

    def test_ignore_annotation_skips_workload(self):
        policy = StoragePolicy(storage_class_name="local-path-ha")
        deployment = {
            "kind": "Deployment",
            "metadata": {
                "name": "operator",
                "annotations": {"storage-ha/ignore": "true"},
            },
            "spec": {
                "template": {
                    "spec": {
                        "volumes": [
                            {"name": "data", "persistentVolumeClaim": {"claimName": "api-data"}}
                        ]
                    }
                }
            },
        }
        pvcs = {"api-data": {"spec": {"storageClassName": "local-path-ha"}}}

        result = reconcile_workload(deployment, pvcs, policy)

        self.assertFalse(result.changed)
        self.assertFalse(result.managed)

    def test_reconcile_is_idempotent(self):
        policy = StoragePolicy(storage_class_name="local-path-ha")
        deployment = {
            "kind": "Deployment",
            "metadata": {"name": "api"},
            "spec": {
                "template": {
                    "spec": {
                        "volumes": [
                            {"name": "data", "persistentVolumeClaim": {"claimName": "api-data"}}
                        ]
                    }
                }
            },
        }
        pvcs = {"api-data": {"spec": {"storageClassName": "local-path-ha"}}}

        first = reconcile_workload(deployment, pvcs, policy)
        second = reconcile_workload(first.workload, pvcs, policy)

        self.assertTrue(first.changed)
        self.assertFalse(second.changed)

    def test_preserves_pod_affinity_and_anti_affinity(self):
        policy = StoragePolicy(storage_class_name="local-path-ha")
        workload = {
            "kind": "Deployment",
            "metadata": {"name": "api"},
            "spec": {
                "template": {
                    "spec": {
                        "volumes": [
                            {"name": "data", "persistentVolumeClaim": {"claimName": "api-data"}}
                        ],
                        "affinity": {
                            "podAffinity": {"preferredDuringSchedulingIgnoredDuringExecution": []},
                            "podAntiAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": []},
                        },
                    }
                }
            },
        }
        pvcs = {"api-data": {"spec": {"storageClassName": "local-path-ha"}}}

        result = reconcile_workload(workload, pvcs, policy)
        affinity = result.workload["spec"]["template"]["spec"]["affinity"]

        self.assertIn("podAffinity", affinity)
        self.assertIn("podAntiAffinity", affinity)


if __name__ == "__main__":
    unittest.main()
