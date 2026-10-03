CREATE TABLE IF NOT EXISTS capabilities (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES distillation_jobs(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    summary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('candidate','in_review','approved','rejected')),
    core_tasks TEXT NOT NULL DEFAULT '[]',
    rules TEXT NOT NULL DEFAULT '[]',
    suggested_packaging TEXT NOT NULL DEFAULT 'skill',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(job_id, name)
);
CREATE TABLE IF NOT EXISTS capability_evidence (
    capability_id TEXT NOT NULL REFERENCES capabilities(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES evidences(id) ON DELETE RESTRICT,
    PRIMARY KEY(capability_id, evidence_id)
);
CREATE TABLE IF NOT EXISTS mechanisms (
    id TEXT PRIMARY KEY,
    capability_id TEXT NOT NULL REFERENCES capabilities(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    description TEXT NOT NULL,
    scope TEXT NOT NULL,
    limitations TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','in_review','approved','rejected')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS mechanism_evidence (
    mechanism_id TEXT NOT NULL REFERENCES mechanisms(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES evidences(id) ON DELETE RESTRICT,
    PRIMARY KEY(mechanism_id, evidence_id)
);
CREATE TABLE IF NOT EXISTS skill_plans (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES distillation_jobs(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('draft','in_review','approved','rejected')),
    trigger_conditions TEXT NOT NULL DEFAULT '[]',
    workflow_outline TEXT NOT NULL DEFAULT '[]',
    decision_logic TEXT NOT NULL DEFAULT '[]',
    boundaries TEXT NOT NULL DEFAULT '[]',
    key_terms TEXT NOT NULL DEFAULT '[]',
    dependencies TEXT NOT NULL DEFAULT '[]',
    review_note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    approved_at TEXT
);
CREATE TABLE IF NOT EXISTS skill_plan_capabilities (
    skill_plan_id TEXT NOT NULL REFERENCES skill_plans(id) ON DELETE CASCADE,
    capability_id TEXT NOT NULL REFERENCES capabilities(id) ON DELETE RESTRICT,
    PRIMARY KEY(skill_plan_id, capability_id)
);
CREATE TABLE IF NOT EXISTS skill_plan_nodes (
    id TEXT PRIMARY KEY,
    skill_plan_id TEXT NOT NULL REFERENCES skill_plans(id) ON DELETE CASCADE,
    node_kind TEXT NOT NULL CHECK(node_kind IN ('instruction','workflow_step','decision_rule','boundary','reference','script','asset')),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    order_index INTEGER NOT NULL CHECK(order_index >= 0)
);
CREATE TABLE IF NOT EXISTS skill_plan_node_evidence (
    node_id TEXT NOT NULL REFERENCES skill_plan_nodes(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES evidences(id) ON DELETE RESTRICT,
    PRIMARY KEY(node_id, evidence_id)
);
CREATE INDEX IF NOT EXISTS idx_capabilities_job_id ON capabilities(job_id);
CREATE INDEX IF NOT EXISTS idx_mechanisms_capability_id ON mechanisms(capability_id);
CREATE INDEX IF NOT EXISTS idx_skill_plans_job_id ON skill_plans(job_id);
CREATE INDEX IF NOT EXISTS idx_skill_plan_nodes_plan_id ON skill_plan_nodes(skill_plan_id);
