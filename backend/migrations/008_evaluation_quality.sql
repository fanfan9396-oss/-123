CREATE TABLE IF NOT EXISTS scenarios (
    id TEXT PRIMARY KEY,
    skill_plan_id TEXT NOT NULL REFERENCES skill_plans(id) ON DELETE CASCADE,
    generated_skill_id TEXT REFERENCES generated_skills(id) ON DELETE SET NULL,
    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
    input_text TEXT NOT NULL CHECK(length(trim(input_text)) > 0),
    boundary_kind TEXT NOT NULL CHECK(boundary_kind IN ('normal','ambiguous','failure','safety_boundary')),
    expected_behavior TEXT NOT NULL CHECK(length(trim(expected_behavior)) > 0),
    forbidden_behavior TEXT NOT NULL CHECK(length(trim(forbidden_behavior)) > 0),
    version_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS evaluations (
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    skill_plan_id TEXT NOT NULL REFERENCES skill_plans(id) ON DELETE CASCADE,
    generated_skill_id TEXT REFERENCES generated_skills(id) ON DELETE SET NULL,
    observed_behavior TEXT NOT NULL CHECK(length(trim(observed_behavior)) > 0),
    verdict TEXT NOT NULL CHECK(verdict IN ('pass','partial','fail','not_run')),
    notes TEXT NOT NULL DEFAULT '',
    evaluator TEXT NOT NULL DEFAULT 'manual',
    version_fingerprint TEXT NOT NULL,
    evaluated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS quality_reports (
    id TEXT PRIMARY KEY,
    generated_skill_id TEXT NOT NULL REFERENCES generated_skills(id) ON DELETE CASCADE,
    traceability_result TEXT NOT NULL CHECK(traceability_result IN ('pass','warn','fail')),
    boundary_result TEXT NOT NULL CHECK(boundary_result IN ('pass','warn','fail')),
    export_result TEXT NOT NULL CHECK(export_result IN ('pass','warn','fail')),
    license_privacy_result TEXT NOT NULL CHECK(license_privacy_result IN ('pass','warn','fail')),
    summary_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK(status IN ('pass','needs_revision','blocked')),
    version_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_scenarios_plan_id ON scenarios(skill_plan_id);
CREATE INDEX IF NOT EXISTS idx_scenarios_generated_id ON scenarios(generated_skill_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_plan_id ON evaluations(skill_plan_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_scenario_id ON evaluations(scenario_id);
CREATE INDEX IF NOT EXISTS idx_quality_reports_generated_id ON quality_reports(generated_skill_id);
