from pathlib import Path

from app.db import MIGRATION_2_SQL, MIGRATION_3_SQL, MIGRATION_4_SQL, MIGRATION_5_SQL, MIGRATION_6_SQL, MIGRATION_7_SQL, MIGRATION_8_SQL


if __name__ == "__main__":
    folder = Path(__file__).resolve().parent
    (folder / "002_distillation_jobs.sql").write_text(MIGRATION_2_SQL.strip() + "\n", encoding="utf-8")
    (folder / "003_document_pending_hash.sql").write_text(MIGRATION_3_SQL.strip() + "\n", encoding="utf-8")
    (folder / "004_evidence.sql").write_text(MIGRATION_4_SQL.strip() + "\n", encoding="utf-8")
    (folder / "005_capability_skill_plan.sql").write_text(MIGRATION_5_SQL.strip() + "\n", encoding="utf-8")
    (folder / "006_skill_plan_mechanisms.sql").write_text(MIGRATION_6_SQL.strip() + "\n", encoding="utf-8")
    print(folder / "002_distillation_jobs.sql")
    print(folder / "003_document_pending_hash.sql")
    print(folder / "004_evidence.sql")
    print(folder / "005_capability_skill_plan.sql")
    (folder / "007_generated_skills_export_runs.sql").write_text(MIGRATION_7_SQL.strip() + "\n", encoding="utf-8")
    (folder / "008_evaluation_quality.sql").write_text(MIGRATION_8_SQL.strip() + "\n", encoding="utf-8")
    print(folder / "006_skill_plan_mechanisms.sql")
    print(folder / "007_generated_skills_export_runs.sql")
    print(folder / "008_evaluation_quality.sql")
