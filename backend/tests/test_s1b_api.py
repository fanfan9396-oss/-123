import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


class ProjectAndSourceUiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Path(self.temp_dir.name) / "workbench.sqlite3"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_snapshot_survives_original_file_removal(self):
        original = Path(self.temp_dir.name) / "source.md"
        original.write_text("原始第一行\n原始第二行\n", encoding="utf-8")
        project_id = self.client.post("/api/projects", json={"name": "快照独立性"}).json()["id"]
        response = self.client.post(
            f"/api/projects/{project_id}/sources",
            json={
                "filename": original.name,
                "content": original.read_text(encoding="utf-8"),
                "original_path": str(original),
            },
        )
        self.assertEqual(response.status_code, 201)
        original.unlink()
        reopened = self.client.get(f"/api/projects/{project_id}")
        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(
            reopened.json()["sources"][0]["snapshot_text"],
            "原始第一行\n原始第二行\n",
        )
    def test_project_list_and_source_flow_are_ready_for_ui(self):
        created = self.client.post("/api/projects", json={"name": "UI 项目", "goal": "目标"})
        self.assertEqual(created.status_code, 201)
        project_id = created.json()["id"]
        source = self.client.post(
            f"/api/projects/{project_id}/sources",
            json={"filename": "source.txt", "content": "A\r\nB"},
        )
        self.assertEqual(source.status_code, 201)
        projects = self.client.get("/api/projects")
        self.assertEqual(projects.status_code, 200)
        opened = self.client.get(f"/api/projects/{project_id}")
        self.assertEqual(opened.json()["sources"][0]["snapshot_text"], "A\nB")


if __name__ == "__main__":
    unittest.main()
