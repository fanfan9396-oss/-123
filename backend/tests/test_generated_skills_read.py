import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


class GeneratedSkillReadTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Path(self.temp_dir.name) / "generated-read.sqlite3"))
        project = self.client.post("/api/projects", json={"name": "GeneratedSkill 读取测试"}).json()
        job = self.client.post(f"/api/projects/{project['id']}/jobs", json={"name": "Job", "input_root": "browser"}).json()
        self.job_id = job["id"]
        self.client.post(f"/api/jobs/{self.job_id}/scan", json={"files": [{"relative_path": "source.md", "filename": "source.md", "format": "md", "size": 4, "content": "来源"}]})
        self.client.post(f"/api/jobs/{self.job_id}/parse")
        excerpt = self.client.get(f"/api/projects/{project['id']}").json()["sources"][0]["excerpt"]["id"]
        evidence = self.client.post(f"/api/jobs/{self.job_id}/evidence", json={"text": "可执行规则", "evidence_type": "workflow_step", "evidence_level": "B", "confidence": 0.9, "scope": "当前 Job", "limitations": "不外推", "excerpt_links": [{"excerpt_id": excerpt, "relation_kind": "direct_support"}]}).json()
        self.client.post(f"/api/evidence/{evidence['id']}/review", json={"action": "approve"})
        cap = self.client.post(f"/api/jobs/{self.job_id}/capabilities", json={"name": "读取能力", "summary": "读取生成版本", "evidence_ids": [evidence["id"]]}).json()
        self.client.post(f"/api/capabilities/{cap['id']}/review", json={"action": "approve"})
        plan = self.client.post(f"/api/jobs/{self.job_id}/skill-plans", json={"name": "读取 Skill", "capability_ids": [cap["id"]], "nodes": [{"node_kind": "workflow_step", "title": "执行", "content": "执行并保留来源"}]}).json()
        self.plan_id = plan["id"]
        self.client.put(f"/api/skill-plans/{self.plan_id}/nodes/0/source-evidence", json={"evidence_ids": [evidence["id"]]})
        self.client.post(f"/api/skill-plans/{self.plan_id}/review", json={"action": "approve"})
        self.generated_id = self.client.post(f"/api/skill-plans/{self.plan_id}/compile-preview").json()["id"]

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_generated_skill_list_and_get_return_preview_without_recompile(self):
        listed = self.client.get(f"/api/skill-plans/{self.plan_id}/generated-skills")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(len(listed.json()), 1)
        self.assertEqual(listed.json()[0]["id"], self.generated_id)
        detail = self.client.get(f"/api/generated-skills/{self.generated_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["id"], self.generated_id)
        self.assertTrue(detail.json()["files"])
        self.assertTrue(detail.json()["source_map"])

    def test_missing_generated_skill_returns_404(self):
        self.assertEqual(self.client.get("/api/generated-skills/missing").status_code, 404)


if __name__ == "__main__":
    unittest.main()
