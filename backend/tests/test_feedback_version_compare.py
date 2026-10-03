import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


class FeedbackVersionCompareTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Path(self.temp_dir.name) / "feedback.sqlite3"))
        self.project_id, self.job_id, self.plan_id, self.generated_one = self._build_plan()
        self.generated_two = self.client.post(f"/api/skill-plans/{self.plan_id}/compile-preview").json()["id"]

    def tearDown(self):
        self.temp_dir.cleanup()

    def _build_plan(self):
        project = self.client.post("/api/projects", json={"name": "反馈对比测试"}).json()
        job = self.client.post(f"/api/projects/{project['id']}/jobs", json={"name": "反馈 Job", "input_root": "browser"}).json()
        self.client.post(f"/api/jobs/{job['id']}/scan", json={"files": [{"relative_path": "source.md", "filename": "source.md", "format": "md", "size": 12, "content": "来源\n边界"}]})
        self.client.post(f"/api/jobs/{job['id']}/parse")
        excerpt = self.client.get(f"/api/projects/{project['id']}").json()["sources"][0]["excerpt"]["id"]
        evidence = self.client.post(f"/api/jobs/{job['id']}/evidence", json={"text": "必须保留边界", "evidence_type": "workflow_step", "evidence_level": "B", "confidence": 0.9, "scope": "当前", "limitations": "不外推", "excerpt_links": [{"excerpt_id": excerpt, "relation_kind": "direct_support"}]}).json()
        self.client.post(f"/api/evidence/{evidence['id']}/review", json={"action": "approve"})
        cap = self.client.post(f"/api/jobs/{job['id']}/capabilities", json={"name": "反馈能力", "summary": "反馈和对比", "evidence_ids": [evidence["id"]]}).json()
        self.client.post(f"/api/capabilities/{cap['id']}/review", json={"action": "approve"})
        plan = self.client.post(f"/api/jobs/{job['id']}/skill-plans", json={"name": "反馈 Skill", "description": "版本比较", "capability_ids": [cap["id"]], "nodes": [{"node_kind": "workflow_step", "title": "边界", "content": "必须说明边界"}]}).json()
        self.client.put(f"/api/skill-plans/{plan['id']}/nodes/0/source-evidence", json={"evidence_ids": [evidence["id"]]})
        self.client.post(f"/api/skill-plans/{plan['id']}/review", json={"action": "approve"})
        generated = self.client.post(f"/api/skill-plans/{plan['id']}/compile-preview").json()
        return project["id"], job["id"], plan["id"], generated["id"]

    def test_feedback_returns_latest_report_targets_without_mutation(self):
        report = self.client.post(f"/api/generated-skills/{self.generated_one}/quality-check").json()
        feedback = self.client.get(f"/api/generated-skills/{self.generated_one}/feedback")
        self.assertEqual(feedback.status_code, 200, feedback.text)
        payload = feedback.json()
        self.assertEqual(payload["generated_skill_id"], self.generated_one)
        self.assertEqual(payload["quality_report_id"], report["id"])
        self.assertIn("items", payload)
        self.assertTrue(any(item["target_kind"] == "SkillPlan" for item in payload["items"]))
        self.assertTrue(all(item["automatic_mutation"] is False for item in payload["items"]))

    def test_feedback_without_report_is_empty(self):
        response = self.client.get(f"/api/generated-skills/{self.generated_two}/feedback")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["items"], [])
        self.assertIsNone(response.json()["quality_report_id"])

    def test_compare_same_plan_returns_file_and_source_map_diff(self):
        response = self.client.get(f"/api/skill-plans/{self.plan_id}/generated-skills/compare", params={"from_id": self.generated_one, "to_id": self.generated_two})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["skill_plan_id"], self.plan_id)
        self.assertEqual(payload["from"]["id"], self.generated_one)
        self.assertEqual(payload["to"]["id"], self.generated_two)
        self.assertIn("files", payload)
        self.assertIn("source_map", payload)
        self.assertIn("quality_reports", payload)
        self.assertTrue(payload["files"]["unchanged"])

    def test_compare_rejects_cross_plan(self):
        _, _, other_plan, other_generated = self._build_plan()
        response = self.client.get(f"/api/skill-plans/{self.plan_id}/generated-skills/compare", params={"from_id": self.generated_one, "to_id": other_generated})
        self.assertEqual(response.status_code, 422, response.text)


if __name__ == "__main__":
    unittest.main()
