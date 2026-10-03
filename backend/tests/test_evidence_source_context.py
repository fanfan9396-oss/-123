import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


class EvidenceSourceContextTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Path(self.temp_dir.name) / "source-context.sqlite3"))
        self.project_id, self.job_id, self.evidence_id, self.excerpt_text, self.snapshot_sha256 = self._make_job("来源定位项目")
        _, self.other_job_id, _, _, _ = self._make_job("另一个项目")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _make_job(self, name: str):
        project = self.client.post("/api/projects", json={"name": name}).json()
        job = self.client.post(f"/api/projects/{project['id']}/jobs", json={"name": f"{name} Job", "input_root": "browser"}).json()
        content = "第一行\n需要保留的原文摘录\n第三行"
        self.client.post(f"/api/jobs/{job['id']}/scan", json={"files": [{"relative_path": "notes/source.md", "filename": "source.md", "format": "md", "size": len(content.encode()), "content": content}]})
        self.client.post(f"/api/jobs/{job['id']}/parse")
        detail = self.client.get(f"/api/projects/{project['id']}").json()
        source = detail["sources"][0]
        excerpt_id = source["excerpt"]["id"]
        evidence = self.client.post(f"/api/jobs/{job['id']}/evidence", json={"text": "原文支持的流程规则", "evidence_type": "workflow_step", "evidence_level": "B", "confidence": 0.9, "scope": "当前资料", "limitations": "不外推", "excerpt_links": [{"excerpt_id": excerpt_id, "relation_kind": "direct_support"}]}).json()
        return project["id"], job["id"], evidence["id"], content, source["snapshot_sha256"]

    def test_source_context_returns_excerpt_source_lines_and_hash_without_mutation(self):
        before = self.client.get(f"/api/projects/{self.project_id}").json()["sources"][0]
        response = self.client.get(f"/api/jobs/{self.job_id}/evidence/{self.evidence_id}/source-context")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["evidence"]["id"], self.evidence_id)
        self.assertEqual(len(payload["links"]), 1)
        link = payload["links"][0]
        self.assertEqual(link["excerpt_text"], self.excerpt_text)
        self.assertEqual(link["start_line"], 1)
        self.assertEqual(link["end_line"], 3)
        self.assertEqual(link["snapshot_sha256"], self.snapshot_sha256)
        self.assertEqual(link["original_path"], "notes/source.md")
        after = self.client.get(f"/api/projects/{self.project_id}").json()["sources"][0]
        self.assertEqual(before["snapshot_text"], after["snapshot_text"])
        self.assertEqual(before["snapshot_sha256"], after["snapshot_sha256"])

    def test_source_context_rejects_cross_job_access(self):
        response = self.client.get(f"/api/jobs/{self.other_job_id}/evidence/{self.evidence_id}/source-context")
        self.assertEqual(response.status_code, 422, response.text)

    def test_missing_evidence_is_not_disclosed(self):
        response = self.client.get(f"/api/jobs/{self.job_id}/evidence/missing/source-context")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

