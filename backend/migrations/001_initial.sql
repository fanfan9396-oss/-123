-- Distillation Workbench schema v1

CREATE TABLE IF NOT EXISTS schema_version (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL CHECK (version >= 1),
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    goal TEXT,
    description TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1 CHECK (schema_version >= 1),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL CHECK (
        source_type IN (
            'research_paper', 'book', 'theory', 'creator_content',
            'official_material', 'case', 'existing_skill', 'other'
        )
    ),
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    author_or_creator TEXT,
    published_at TEXT,
    source_uri TEXT,
    original_path TEXT,
    notes TEXT,
    format TEXT NOT NULL CHECK (format IN ('md', 'txt')),
    snapshot_text TEXT NOT NULL CHECK (length(snapshot_text) > 0),
    snapshot_sha256 TEXT NOT NULL CHECK (length(snapshot_sha256) = 64),
    original_file_sha256 TEXT,
    imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(project_id, snapshot_sha256)
);

CREATE TABLE IF NOT EXISTS excerpts (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    start_line INTEGER NOT NULL CHECK (start_line >= 1),
    end_line INTEGER NOT NULL CHECK (end_line >= start_line),
    excerpt_text TEXT NOT NULL CHECK (length(excerpt_text) > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_sources_project_id ON sources(project_id);
CREATE INDEX IF NOT EXISTS idx_excerpts_source_id ON excerpts(source_id);
