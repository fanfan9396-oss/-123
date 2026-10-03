CREATE TABLE IF NOT EXISTS evidences (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES distillation_jobs(id) ON DELETE CASCADE,
    text TEXT NOT NULL CHECK (length(trim(text)) > 0),
    evidence_type TEXT NOT NULL CHECK (evidence_type IN ('workflow_step','decision_rule','capability_hint','terminology','dependency','exception','quantitative_signal')),
    evidence_class TEXT NOT NULL DEFAULT 'unassessed',
    evidence_level TEXT NOT NULL CHECK (evidence_level IN ('A','B','C','D','unassessed')),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    scope TEXT NOT NULL,
    limitations TEXT NOT NULL,
    capability_hint TEXT,
    workflow_steps TEXT NOT NULL DEFAULT '[]',
    decision_rules TEXT NOT NULL DEFAULT '[]',
    terminology TEXT NOT NULL DEFAULT '[]',
    dependencies TEXT NOT NULL DEFAULT '[]',
    exceptions TEXT NOT NULL DEFAULT '[]',
    quantitative_signals TEXT NOT NULL DEFAULT '[]',
    review_status TEXT NOT NULL CHECK (review_status IN ('draft','in_review','approved','rejected')),
    created_origin TEXT NOT NULL CHECK (created_origin IN ('manual','local_rule','model_candidate')),
    review_note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    approved_at TEXT
);
CREATE TABLE IF NOT EXISTS evidence_excerpts (
    evidence_id TEXT NOT NULL REFERENCES evidences(id) ON DELETE CASCADE,
    excerpt_id TEXT NOT NULL REFERENCES excerpts(id) ON DELETE CASCADE,
    relation_kind TEXT NOT NULL CHECK (relation_kind IN ('direct_support','context','limitation','counterexample')),
    PRIMARY KEY (evidence_id, excerpt_id, relation_kind)
);
CREATE INDEX IF NOT EXISTS idx_evidences_job_id ON evidences(job_id);
CREATE INDEX IF NOT EXISTS idx_evidence_excerpts_excerpt_id ON evidence_excerpts(excerpt_id);
