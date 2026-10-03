import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


class EvidenceApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Path(self.temp_dir.name) / "workbench.sqlite3"))
        project = self.client.post("/api/projects", json={"name": "Evidence 测试"})
        self.project_id = project.json()["id"]
        job = self.client.post(f"/api/projects/{self.project_id}/jobs", json={"name": "Evidence Job", "input_root": "browser"})
        self.job_id = job.json()["id"]
        scanned = self.client.post(f"/api/jobs/{self.job_id}/scan", json={"files":[{"relative_path":"source.md","filename":"source.md","format":"md","size":20,"content":"原文第一行\n原文第二行"}]})
        self.assertEqual(scanned.status_code, 200, scanned.text)
        parsed = self.client.post(f"/api/jobs/{self.job_id}/parse")
        self.assertEqual(parsed.json()["status"], "ready_for_evidence")
        self.source_id = parsed.json()["documents"][0]["source_id"]
        self.excerpt_id = self.client.get(f"/api/projects/{self.project_id}").json()["sources"][0]["excerpt"]["id"]

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_review_approve_and_source_map(self):
        created = self.client.post(
            f"/api/jobs/{self.job_id}/evidence",
            json={
                "text": "这是一条可审核的流程证据",
                "evidence_type": "workflow_step",
                "evidence_level": "B",
                "confidence": 0.8,
                "scope": "当前资料中的本地流程",
                "limitations": "不能外推到所有项目",
                "capability_hint": "资料解析",
                "excerpt_links":[{"excerpt_id": self.excerpt_id, "relation_kind":"direct_support"}],
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        evidence_id = created.json()["id"]
        self.assertEqual(created.json()["review_status"], "draft")
        reviewed = self.client.post(f"/api/evidence/{evidence_id}/review", json={"action":"approve", "note":"来源和限制已检查"})
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["review_status"], "approved")
        source_map = self.client.get(f"/api/evidence/{evidence_id}/source-map")
        self.assertEqual(source_map.status_code, 200)
        self.assertEqual(source_map.json()["evidence"]["id"], evidence_id)
        self.assertEqual(source_map.json()["links"][0]["source_id"], self.source_id)

    def test_approval_requires_excerpt_and_reject_preserves_reason(self):
        created = self.client.post(
            f"/api/jobs/{self.job_id}/evidence",
            json={"text":"没有来源的候选", "evidence_type":"decision_rule", "evidence_level":"C", "confidence":0.4, "scope":"范围", "limitations":"限制"},
        )
        evidence_id = created.json()["id"]
        blocked = self.client.post(f"/api/evidence/{evidence_id}/review", json={"action":"approve"})
        self.assertEqual(blocked.status_code, 422)
        rejected = self.client.post(f"/api/evidence/{evidence_id}/review", json={"action":"reject", "note":"缺少来源摘录"})
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["review_status"], "rejected")
        self.assertEqual(rejected.json()["review_note"], "缺少来源摘录")

    def test_cross_job_excerpt_is_rejected(self):
        second = self.client.post(f"/api/projects/{self.project_id}/jobs", json={"name":"第二任务", "input_root":"browser"}).json()["id"]
        created = self.client.post(
            f"/api/jobs/{second}/evidence",
            json={"text":"跨任务证据", "evidence_type":"workflow_step", "evidence_level":"B", "confidence":0.5, "scope":"范围", "limitations":"限制", "excerpt_links":[{"excerpt_id":self.excerpt_id,"relation_kind":"direct_support"}]},
        )
        self.assertEqual(created.status_code, 422)


if __name__ == "__main__":
    unittest.main()
