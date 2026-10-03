CREATE TABLE IF NOT EXISTS distillation_jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    goal TEXT,
    status TEXT NOT NULL CHECK (status IN ('draft', 'scanning', 'parsing', 'review_input', 'ready_for_evidence', 'failed', 'cancelled')),
    current_stage TEXT NOT NULL CHECK (current_stage IN ('scan', 'parse', 'review_input', 'ready')),
    input_root TEXT NOT NULL,
    input_manifest TEXT NOT NULL DEFAULT '[]',
    error_summary TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES distillation_jobs(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
    relative_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    format TEXT NOT NULL CHECK (format IN ('md', 'txt')),
    file_size INTEGER NOT NULL CHECK (file_size >= 0),
    status TEXT NOT NULL CHECK (status IN ('discovered', 'parsed', 'failed', 'skipped')),
    content_sha256 TEXT,
    normalized_text TEXT,
    pending_text TEXT,
    line_count INTEGER CHECK (line_count IS NULL OR line_count >= 1),
    title TEXT,
    parse_error TEXT,
    original_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(job_id, relative_path)
);

CREATE TABLE IF NOT EXISTS job_events (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES distillation_jobs(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_project_id ON distillation_jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_documents_job_id ON documents(job_id);
CREATE INDEX IF NOT EXISTS idx_documents_source_id ON documents(source_id);
CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id);
