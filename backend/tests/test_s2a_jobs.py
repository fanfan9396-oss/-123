import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


class JobAndParsingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Path(self.temp_dir.name) / "workbench.sqlite3"))
        project = self.client.post("/api/projects", json={"name": "Job 测试", "goal": "测试解析"})
        self.assertEqual(project.status_code, 201)
        self.project_id = project.json()["id"]

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_job(self):
        response = self.client.post(
            f"/api/projects/{self.project_id}/jobs",
            json={"name": "第一轮解析", "goal": "提取资料结构", "input_root": "browser-file-picker"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def _scan(self, job_id, files):
        return self.client.post(f"/api/jobs/{job_id}/scan", json={"files": files})

    def test_create_scan_parse_and_reopen_job(self):
        job_id = self._create_job()
        scanned = self._scan(job_id, [
            {"relative_path": "set/a.md", "filename": "a.md", "format": "md", "size": 22, "content": "标题\r\n第一段\r\n"},
            {"relative_path": "set/b.txt", "filename": "b.txt", "format": "txt", "size": 13, "content": "第二份\n内容"},
            {"relative_path": "set/ignored.pdf", "filename": "ignored.pdf", "format": "pdf", "size": 4, "content": "skip"},
        ])
        self.assertEqual(scanned.status_code, 200, scanned.text)
        self.assertEqual(scanned.json()["status"], "review_input")
        self.assertEqual(scanned.json()["manifest_count"], 2)
        self.assertEqual(scanned.json()["unsupported_count"], 1)

        parsed = self.client.post(f"/api/jobs/{job_id}/parse")
        self.assertEqual(parsed.status_code, 200, parsed.text)
        self.assertEqual(parsed.json()["status"], "ready_for_evidence")
        self.assertEqual(parsed.json()["document_counts"]["parsed"], 2)

        detail = self.client.get(f"/api/jobs/{job_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.json()["documents"]), 2)
        self.assertTrue(all(item["status"] == "parsed" for item in detail.json()["documents"]))
        self.assertTrue(all(item["source_id"] for item in detail.json()["documents"]))
        self.assertEqual(detail.json()["events"][-1]["stage"], "parse")
        self.assertNotIn("pending_text", detail.json()["documents"][0])

    def test_parse_failure_does_not_become_ready_and_can_be_skipped_with_reason(self):
        job_id = self._create_job()
        scanned = self._scan(job_id, [
            {"relative_path": "ok.md", "filename": "ok.md", "format": "md", "size": 6, "content": "可解析"},
            {"relative_path": "bad.txt", "filename": "bad.txt", "format": "txt", "size": 5, "error": "文件无法按 UTF-8 解码"},
        ])
        self.assertEqual(scanned.status_code, 200)
        parsed = self.client.post(f"/api/jobs/{job_id}/parse")
        self.assertEqual(parsed.json()["status"], "review_input")
        self.assertEqual(parsed.json()["document_counts"]["failed"], 1)
        self.assertNotEqual(parsed.json()["status"], "ready_for_evidence")
        no_reason = self.client.post(f"/api/jobs/{job_id}/skip-failed", json={"reason": " "})
        self.assertEqual(no_reason.status_code, 422)
        skipped = self.client.post(f"/api/jobs/{job_id}/skip-failed", json={"reason": "用户确认跳过损坏文件"})
        self.assertEqual(skipped.status_code, 200, skipped.text)
        self.assertEqual(skipped.json()["status"], "ready_for_evidence")
        self.assertEqual(skipped.json()["document_counts"]["skipped"], 1)

    def test_rejects_path_traversal_duplicate_paths_oversize_and_missing_project(self):
        job_id = self._create_job()
        traversal = self._scan(job_id, [
            {"relative_path": "../secret.md", "filename": "secret.md", "format": "md", "size": 3, "content": "bad"}
        ])
        self.assertEqual(traversal.status_code, 422)

        duplicate = self._scan(job_id, [
            {"relative_path": "a.md", "filename": "a.md", "format": "md", "size": 1, "content": "a"},
            {"relative_path": "a.md", "filename": "again.md", "format": "md", "size": 1, "content": "b"},
        ])
        self.assertEqual(duplicate.status_code, 422)

        oversized = self._scan(job_id, [
            {"relative_path": "large.md", "filename": "large.md", "format": "md", "size": 6 * 1024 * 1024, "content": "x"}
        ])
        self.assertEqual(oversized.status_code, 422)

        missing = self.client.post(
            "/api/projects/missing/jobs",
            json={"name": "不存在", "input_root": "browser-file-picker"},
        )
        self.assertEqual(missing.status_code, 404)

    def test_empty_manifest_and_unsupported_only_manifest_fail_explicitly(self):
        job_id = self._create_job()
        empty = self._scan(job_id, [])
        self.assertEqual(empty.json()["status"], "failed")
        self.assertIn("没有找到", empty.json()["error_summary"])


if __name__ == "__main__":
    unittest.main()
