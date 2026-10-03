import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


class CompilerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Path(self.temp_dir.name) / "s4.sqlite3"))
        self.project_id = self.client.post("/api/projects", json={"name": "S4 测试"}).json()["id"]
        job = self.client.post(f"/api/projects/{self.project_id}/jobs", json={"name": "Compiler Job", "input_root": "browser"})
        self.job_id = job.json()["id"]
        self.client.post(f"/api/jobs/{self.job_id}/scan", json={"files":[{"relative_path":"source.md","filename":"source.md","format":"md","size":8,"content":"来源内容"}]})
        self.client.post(f"/api/jobs/{self.job_id}/parse")
        self.excerpt_id = self.client.get(f"/api/projects/{self.project_id}").json()["sources"][0]["excerpt"]["id"]
        evidence = self.client.post(f"/api/jobs/{self.job_id}/evidence", json={"text":"可执行流程步骤","evidence_type":"workflow_step","evidence_level":"B","confidence":0.9,"scope":"本项目","limitations":"不外推","excerpt_links":[{"excerpt_id":self.excerpt_id,"relation_kind":"direct_support"}]}).json()
        self.evidence_id = evidence["id"]
        self.client.post(f"/api/evidence/{self.evidence_id}/review", json={"action":"approve"})
        capability = self.client.post(f"/api/jobs/{self.job_id}/capabilities", json={"name":"资料解析能力","summary":"把资料解析为结构化输入","evidence_ids":[self.evidence_id]}).json()
        self.capability_id = capability["id"]
        self.client.post(f"/api/capabilities/{self.capability_id}/review", json={"action":"approve"})
        plan = self.client.post(f"/api/jobs/{self.job_id}/skill-plans", json={"name":"本地资料解析 Skill","description":"编译前计划","capability_ids":[self.capability_id],"nodes":[{"node_kind":"workflow_step","title":"读取输入","content":"读取用户明确选择的 Markdown/TXT 输入"}]}).json()
        self.plan_id = plan["id"]
        self.client.put(f"/api/skill-plans/{self.plan_id}/nodes/0/source-evidence", json={"evidence_ids":[self.evidence_id]})
        self.client.post(f"/api/skill-plans/{self.plan_id}/review", json={"action":"approve"})

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_unapproved_plan_is_blocked_and_approved_plan_previews(self):
        preview = self.client.post(f"/api/skill-plans/{self.plan_id}/compile-preview")
        self.assertEqual(preview.status_code, 200, preview.text)
        generated = preview.json()
        self.assertEqual(generated["status"], "preview")
        paths = {item["path"] for item in generated["files"]}
        self.assertIn("SKILL.md", paths)
        self.assertTrue(any(path.startswith("references/") for path in paths))
        self.assertTrue(generated["source_map"])

    def test_preview_has_no_export_side_effect_and_export_requires_confirmation(self):
        preview = self.client.post(f"/api/skill-plans/{self.plan_id}/compile-preview").json()
        generated_id = preview["id"]
        target = Path(self.temp_dir.name) / "exports" / "skill"
        blocked = self.client.post(f"/api/generated-skills/{generated_id}/export", json={"output_path": str(target), "overwrite": False, "confirm": False})
        self.assertEqual(blocked.status_code, 422)
        self.assertFalse(target.exists())
        exported = self.client.post(f"/api/generated-skills/{generated_id}/export", json={"output_path": str(target), "overwrite": False, "confirm": True})
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertTrue((target / "SKILL.md").exists())
        self.assertTrue((target / "references" / "source-map.json").exists())
        self.assertEqual(exported.json()["status"], "exported")

    def test_existing_output_is_not_overwritten_without_confirmation(self):
        preview = self.client.post(f"/api/skill-plans/{self.plan_id}/compile-preview").json()
        target = Path(self.temp_dir.name) / "exports" / "existing"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("old", encoding="utf-8")
        blocked = self.client.post(f"/api/generated-skills/{preview['id']}/export", json={"output_path": str(target), "overwrite": False, "confirm": True})
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), "old")


if __name__ == "__main__":
    unittest.main()
