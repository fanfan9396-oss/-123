import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


class CapabilityAndSkillPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Path(self.temp_dir.name) / "s3.sqlite3"))
        self.project_id = self.client.post("/api/projects", json={"name": "S3 测试"}).json()["id"]
        job = self.client.post(f"/api/projects/{self.project_id}/jobs", json={"name": "S3 Job", "input_root": "browser"})
        self.job_id = job.json()["id"]
        scan = self.client.post(f"/api/jobs/{self.job_id}/scan", json={"files": [{"relative_path":"source.md","filename":"source.md","format":"md","size":8,"content":"有来源内容"}]})
        self.assertEqual(scan.status_code, 200, scan.text)
        ready = self.client.post(f"/api/jobs/{self.job_id}/parse")
        self.assertEqual(ready.json()["status"], "ready_for_evidence")
        self.excerpt_id = self.client.get(f"/api/projects/{self.project_id}").json()["sources"][0]["excerpt"]["id"]

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_evidence(self, text: str, approved: bool = True) -> str:
        response = self.client.post(f"/api/jobs/{self.job_id}/evidence", json={
            "text": text,
            "evidence_type": "workflow_step",
            "evidence_level": "B",
            "confidence": 0.8,
            "scope": "当前任务资料",
            "limitations": "不向外推断",
            "excerpt_links": [{"excerpt_id": self.excerpt_id, "relation_kind": "direct_support"}],
        })
        self.assertEqual(response.status_code, 201, response.text)
        evidence_id = response.json()["id"]
        if approved:
            result = self.client.post(f"/api/evidence/{evidence_id}/review", json={"action":"approve", "note":"已审核"})
            self.assertEqual(result.status_code, 200, result.text)
        return evidence_id

    def test_capability_merge_keeps_only_approved_evidence(self):
        first = self.create_evidence("first approved evidence")
        second = self.create_evidence("second approved evidence")
        cap_a = self.client.post(f"/api/jobs/{self.job_id}/capabilities", json={"name":"第一能力","evidence_ids":[first]})
        cap_b = self.client.post(f"/api/jobs/{self.job_id}/capabilities", json={"name":"第二能力","evidence_ids":[second]})
        self.assertEqual(cap_a.status_code, 201, cap_a.text)
        self.assertEqual(cap_b.status_code, 201, cap_b.text)
        merged = self.client.post(f"/api/jobs/{self.job_id}/capabilities/merge", json={"capability_ids":[cap_a.json()["id"],cap_b.json()["id"]],"name":"合并能力","summary":"合并摘要"})
        self.assertEqual(merged.status_code, 200, merged.text)
        self.assertEqual(set(merged.json()["evidence_ids"]), {first, second})
        mechanism = self.client.post(
            f"/api/capabilities/{cap_a.json()['id']}/mechanisms",
            json={"name":"旧能力机制","description":"解释","scope":"范围","limitations":"限制","evidence_ids":[first]},
        )
        self.assertEqual(mechanism.status_code, 201, mechanism.text)
        self.assertEqual(merged.json()["status"], "candidate")
        merged_again = self.client.post(
            f"/api/jobs/{self.job_id}/capabilities/merge",
            json={"capability_ids":[merged.json()["id"], cap_a.json()["id"]],"name":"最终合并","summary":"摘要"},
        )
        self.assertEqual(merged_again.status_code, 200, merged_again.text)
        current = self.client.get(f"/api/jobs/{self.job_id}/capabilities").json()
        target = next(item for item in current if item["id"] == merged_again.json()["id"])
        self.assertEqual(target["mechanisms"][0]["id"], mechanism.json()["id"])

    def test_mechanism_requires_approved_capability_and_skill_plan_links_approved_mechanism(self):
        evidence_id = self.create_evidence("mechanism support")
        cap = self.client.post(f"/api/jobs/{self.job_id}/capabilities", json={"name":"能力","evidence_ids":[evidence_id]})
        capability_id = cap.json()["id"]
        blocked = self.client.post(f"/api/capabilities/{capability_id}/mechanisms", json={"name":"机制","description":"说明","scope":"范围","limitations":"限制","evidence_ids":[evidence_id]})
        self.assertEqual(blocked.status_code, 201, blocked.text)
        mechanism_id = blocked.json()["id"]
        not_approved = self.client.post(f"/api/mechanisms/{mechanism_id}/review", json={"action":"approve"})
        self.assertEqual(not_approved.status_code, 422)
        approved_cap = self.client.post(f"/api/capabilities/{capability_id}/review", json={"action":"approve","note":"checked"})
        self.assertEqual(approved_cap.status_code, 200)
        approved_mechanism = self.client.post(f"/api/mechanisms/{mechanism_id}/review", json={"action":"approve","note":"checked"})
        self.assertEqual(approved_mechanism.status_code, 200, approved_mechanism.text)
        plan = self.client.post(f"/api/jobs/{self.job_id}/skill-plans", json={"name":"计划","capability_ids":[capability_id],"mechanism_ids":[mechanism_id],"nodes":[{"node_kind":"workflow_step","title":"步骤","content":"执行","order_index":0}]})
        self.assertEqual(plan.status_code, 201, plan.text)
        self.assertEqual(plan.json()["mechanisms"][0]["id"], mechanism_id)
    def test_capability_cluster_uses_only_approved_evidence_and_has_source_map(self):
        approved = self.create_evidence("approved workflow step")
        self.create_evidence("draft workflow step", approved=False)
        response = self.client.post(f"/api/jobs/{self.job_id}/capabilities/cluster")
        self.assertEqual(response.status_code, 200, response.text)
        candidates = response.json()["capabilities"]
        self.assertTrue(candidates)
        all_ids = {evidence_id for item in candidates for evidence_id in item["evidence_ids"]}
        self.assertIn(approved, all_ids)
        self.assertEqual(len(all_ids), 1)
        capability_id = candidates[0]["id"]
        source_map = self.client.get(f"/api/capabilities/{capability_id}/source-map")
        self.assertEqual(source_map.status_code, 200, source_map.text)
        self.assertEqual(source_map.json()["evidence"][0]["id"], approved)

    def test_skill_plan_cannot_be_approved_without_provenance(self):
        created = self.client.post(f"/api/jobs/{self.job_id}/skill-plans", json={
            "name":"来源可追溯计划",
            "description":"测试计划",
            "capability_ids": [],
            "nodes":[{"node_kind":"workflow_step","title":"无来源节点","content":"执行一步"}],
        })
        self.assertEqual(created.status_code, 201, created.text)
        plan_id = created.json()["id"]
        result = self.client.post(f"/api/skill-plans/{plan_id}/review", json={"action":"approve"})
        self.assertEqual(result.status_code, 422)

    def test_skill_plan_source_map_and_approved_capability_gate(self):
        evidence_id = self.create_evidence("approved capability support")
        cluster = self.client.post(f"/api/jobs/{self.job_id}/capabilities/cluster")
        capability_id = cluster.json()["capabilities"][0]["id"]
        capability_review = self.client.post(f"/api/capabilities/{capability_id}/review", json={"action":"approve", "note":"聚类已审核"})
        self.assertEqual(capability_review.status_code, 200, capability_review.text)
        plan = self.client.post(f"/api/jobs/{self.job_id}/skill-plans", json={
            "name":"来源驱动技能计划",
            "description":"将能力编排为 Skill 工作流",
            "capability_ids":[capability_id],
            "nodes":[{"node_kind":"workflow_step","title":"处理输入","content":"先识别输入"}],
        })
        self.assertEqual(plan.status_code, 201, plan.text)
        plan_id = plan.json()["id"]
        before = self.client.post(f"/api/skill-plans/{plan_id}/review", json={"action":"approve"})
        self.assertEqual(before.status_code, 422)
        updated = self.client.put(f"/api/skill-plans/{plan_id}/nodes/0/source-evidence", json={"evidence_ids":[evidence_id]})
        self.assertEqual(updated.status_code, 200, updated.text)
        source_map = self.client.get(f"/api/skill-plans/{plan_id}/source-map")
        self.assertEqual(source_map.status_code, 200, source_map.text)
        self.assertEqual(source_map.json()["nodes"][0]["evidence_ids"], [evidence_id])
        approved = self.client.post(f"/api/skill-plans/{plan_id}/review", json={"action":"approve", "note":"来源链完整"})
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["status"], "approved")


if __name__ == "__main__":
    unittest.main()
