CREATE TABLE IF NOT EXISTS generated_skills (
    id TEXT PRIMARY KEY,
    skill_plan_id TEXT NOT NULL REFERENCES skill_plans(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK(status IN ('preview','approved_for_export','exported','failed','cancelled')),
    file_manifest TEXT NOT NULL DEFAULT '[]',
    source_map TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS export_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    skill_plan_id TEXT NOT NULL REFERENCES skill_plans(id) ON DELETE CASCADE,
    format TEXT NOT NULL DEFAULT 'skill_package',
    scope_json TEXT NOT NULL DEFAULT '{}',
    output_path TEXT,
    output_sha256 TEXT,
    status TEXT NOT NULL CHECK(status IN ('preview','approved_for_export','exported','failed','cancelled')),
    error_summary TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_generated_skills_plan_id ON generated_skills(skill_plan_id);
CREATE INDEX IF NOT EXISTS idx_export_runs_plan_id ON export_runs(skill_plan_id);
