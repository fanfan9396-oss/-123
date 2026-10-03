import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


class S5EvaluationQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "s5.sqlite3"
        self.client = TestClient(create_app(self.db_path))
        self.project_id, self.job_id, self.evidence_id, self.capability_id, self.plan_id, self.generated_id = self._build_approved_plan("S5 测试")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _build_approved_plan(self, project_name: str):
        project_id = self.client.post("/api/projects", json={"name": project_name}).json()["id"]
        job_id = self.client.post(f"/api/projects/{project_id}/jobs", json={"name": f"{project_name} Job", "input_root": "browser"}).json()["id"]
        self.client.post(
            f"/api/jobs/{job_id}/scan",
            json={"files": [{"relative_path": "source.md", "filename": "source.md", "format": "md", "size": 20, "content": "来源内容\n包含边界和限制"}]},
        )
        self.client.post(f"/api/jobs/{job_id}/parse")
        excerpt_id = self.client.get(f"/api/projects/{project_id}").json()["sources"][0]["excerpt"]["id"]
        evidence = self.client.post(
            f"/api/jobs/{job_id}/evidence",
            json={
                "text": "回答必须保留边界、来源和停止条件",
                "evidence_type": "workflow_step",
                "evidence_level": "B",
                "confidence": 0.9,
                "scope": "本地 Skill 生成",
                "limitations": "不能外推到未审核来源",
                "excerpt_links": [{"excerpt_id": excerpt_id, "relation_kind": "direct_support"}],
            },
        ).json()
        evidence_id = evidence["id"]
        self.client.post(f"/api/evidence/{evidence_id}/review", json={"action": "approve"})
        capability = self.client.post(
            f"/api/jobs/{job_id}/capabilities",
            json={"name": "质量评测能力", "summary": "用可追溯场景检查 Skill", "evidence_ids": [evidence_id]},
        ).json()
        capability_id = capability["id"]
        self.client.post(f"/api/capabilities/{capability_id}/review", json={"action": "approve"})
        plan = self.client.post(
            f"/api/jobs/{job_id}/skill-plans",
            json={
                "name": f"{project_name} SkillPlan",
                "description": "带边界的质量评测计划",
                "capability_ids": [capability_id],
                "nodes": [
                    {"node_kind": "workflow_step", "title": "保留来源", "content": "输出必须说明来源、限制和停止条件。"},
                    {"node_kind": "boundary", "title": "隐私边界", "content": "不得泄露私密路径、密钥或未授权原文。"},
                ],
            },
        ).json()
        plan_id = plan["id"]
        self.client.put(f"/api/skill-plans/{plan_id}/nodes/0/source-evidence", json={"evidence_ids": [evidence_id]})
        self.client.put(f"/api/skill-plans/{plan_id}/nodes/1/source-evidence", json={"evidence_ids": [evidence_id]})
        self.client.post(f"/api/skill-plans/{plan_id}/review", json={"action": "approve"})
        generated_id = self.client.post(f"/api/skill-plans/{plan_id}/compile-preview").json()["id"]
        return project_id, job_id, evidence_id, capability_id, plan_id, generated_id

    def test_create_four_scenario_kinds_and_bind_to_generated_skill_version(self):
        created = []
        for kind in ["normal", "ambiguous", "failure", "safety_boundary"]:
            response = self.client.post(
                f"/api/skill-plans/{self.plan_id}/scenarios",
                json={
                    "generated_skill_id": self.generated_id,
                    "title": f"{kind} 场景",
                    "input_text": f"输入 {kind}",
                    "boundary_kind": kind,
                    "expected_behavior": "说明依据和限制",
                    "forbidden_behavior": "不得编造来源",
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            created.append(response.json())
        scenarios = self.client.get(f"/api/skill-plans/{self.plan_id}/scenarios").json()
        self.assertEqual(len(scenarios), 4)
        self.assertTrue(all(item["generated_skill_id"] == self.generated_id for item in scenarios))
        self.assertTrue(all(item["version_fingerprint"] for item in scenarios))
        invalid = self.client.post(
            f"/api/skill-plans/{self.plan_id}/scenarios",
            json={"generated_skill_id": self.generated_id, "title": "坏类型", "input_text": "x", "boundary_kind": "bad", "expected_behavior": "x", "forbidden_behavior": "x"},
        )
        self.assertEqual(invalid.status_code, 422)

    def test_evaluation_verdict_validation_and_no_business_knowledge_mutation(self):
        scenario = self.client.post(
            f"/api/skill-plans/{self.plan_id}/scenarios",
            json={"generated_skill_id": self.generated_id, "title": "正常", "input_text": "用户输入", "boundary_kind": "normal", "expected_behavior": "保留来源", "forbidden_behavior": "不编造"},
        ).json()
        before_evidence = self.client.get(f"/api/jobs/{self.job_id}/evidence").json()
        before_capabilities = self.client.get(f"/api/jobs/{self.job_id}/capabilities").json()
        before_plan = self.client.get(f"/api/skill-plans/{self.plan_id}").json()
        invalid = self.client.post(f"/api/scenarios/{scenario['id']}/evaluate", json={"observed_behavior": "x", "verdict": "great", "notes": "x", "evaluator": "tester"})
        self.assertEqual(invalid.status_code, 422)
        evaluated = self.client.post(
            f"/api/scenarios/{scenario['id']}/evaluate",
            json={"observed_behavior": "回答包含来源但边界略少", "verdict": "partial", "notes": "需要补边界", "evaluator": "tester"},
        )
        self.assertEqual(evaluated.status_code, 201, evaluated.text)
        payload = evaluated.json()
        self.assertEqual(payload["skill_plan_id"], self.plan_id)
        self.assertEqual(payload["generated_skill_id"], self.generated_id)
        self.assertEqual(payload["verdict"], "partial")
        evaluations = self.client.get(f"/api/skill-plans/{self.plan_id}/evaluations").json()
        self.assertEqual(len(evaluations), 1)
        self.assertEqual(before_evidence, self.client.get(f"/api/jobs/{self.job_id}/evidence").json())
        self.assertEqual(before_capabilities, self.client.get(f"/api/jobs/{self.job_id}/capabilities").json())
        self.assertEqual(before_plan, self.client.get(f"/api/skill-plans/{self.plan_id}").json())

    def test_cross_plan_generated_skill_binding_is_rejected(self):
        _, _, _, _, other_plan_id, other_generated_id = self._build_approved_plan("另一个项目")
        response = self.client.post(
            f"/api/skill-plans/{self.plan_id}/scenarios",
            json={"generated_skill_id": other_generated_id, "title": "跨项目", "input_text": "x", "boundary_kind": "normal", "expected_behavior": "x", "forbidden_behavior": "x"},
        )
        self.assertEqual(response.status_code, 422)
        ok = self.client.post(
            f"/api/skill-plans/{other_plan_id}/scenarios",
            json={"generated_skill_id": other_generated_id, "title": "同项目", "input_text": "x", "boundary_kind": "normal", "expected_behavior": "x", "forbidden_behavior": "x"},
        )
        self.assertEqual(ok.status_code, 201, ok.text)

    def test_quality_report_is_deterministic_and_detects_missing_source_map(self):
        self.assertEqual(self.client.get(f"/api/generated-skills/{self.generated_id}/quality-report").status_code, 200)
        self.assertIsNone(self.client.get(f"/api/generated-skills/{self.generated_id}/quality-report").json())
        report = self.client.post(f"/api/generated-skills/{self.generated_id}/quality-check")
        self.assertEqual(report.status_code, 200, report.text)
        first = report.json()
        self.assertEqual(first["generated_skill_id"], self.generated_id)
        self.assertEqual(first["traceability_result"], "pass")
        self.assertEqual(first["license_privacy_result"], "pass")
        self.assertIn(first["status"], {"pass", "needs_revision"})
        latest = self.client.get(f"/api/generated-skills/{self.generated_id}/quality-report").json()
        self.assertEqual(first["id"], latest["id"])
        self.client.post(f"/api/generated-skills/{self.generated_id}/quality-check")
        connection = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM quality_reports WHERE generated_skill_id=?", (self.generated_id,)).fetchone()[0], 2)
            connection.execute("UPDATE generated_skills SET source_map='{}' WHERE id=?", (self.generated_id,))
            connection.commit()
        finally:
            connection.close()
        broken = self.client.post(f"/api/generated-skills/{self.generated_id}/quality-check").json()
        self.assertEqual(broken["traceability_result"], "fail")
        self.assertEqual(broken["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
