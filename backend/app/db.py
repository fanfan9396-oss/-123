"""SQLite persistence for the local distillation workbench."""

from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 8


class DatabaseError(RuntimeError):
    """Raised when a database cannot be safely initialized or migrated."""


BASE_SCHEMA_SQL = """
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
"""

MIGRATION_2_SQL = """
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
"""

MIGRATION_3_SQL = "ALTER TABLE documents ADD COLUMN pending_file_sha256 TEXT;\n"




MIGRATION_4_SQL = """
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
"""


MIGRATION_6_SQL = """
ALTER TABLE mechanisms ADD COLUMN review_note TEXT;
CREATE TABLE IF NOT EXISTS skill_plan_mechanisms (
    skill_plan_id TEXT NOT NULL REFERENCES skill_plans(id) ON DELETE CASCADE,
    mechanism_id TEXT NOT NULL REFERENCES mechanisms(id) ON DELETE RESTRICT,
    PRIMARY KEY(skill_plan_id, mechanism_id)
);
CREATE INDEX IF NOT EXISTS idx_skill_plan_mechanisms_mechanism_id ON skill_plan_mechanisms(mechanism_id);
"""

MIGRATION_5_SQL = """
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
"""

MIGRATION_7_SQL = """
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
"""

MIGRATION_8_SQL = """
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
"""

SCHEMA_SQL = BASE_SCHEMA_SQL + "\n" + MIGRATION_2_SQL + MIGRATION_3_SQL + MIGRATION_4_SQL + MIGRATION_5_SQL + MIGRATION_6_SQL + MIGRATION_7_SQL + MIGRATION_8_SQL


def connect_database(path: Path | str) -> sqlite3.Connection:
    connection = sqlite3.connect(Path(path), isolation_level="DEFERRED")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _user_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


def _read_version(connection: sqlite3.Connection) -> int | None:
    if "schema_version" not in _user_tables(connection):
        return None
    row = connection.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    return None if row is None else int(row[0])


def initialize_database(path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect_database(target)) as connection:
        version = _read_version(connection)
        tables = _user_tables(connection)
        if version == SCHEMA_VERSION:
            return
        if version is None and tables:
            raise DatabaseError("existing database has no registered schema version; refusing to overwrite it")
        try:
            with connection:
                if version is None:
                    connection.executescript(SCHEMA_SQL)
                    connection.execute("INSERT INTO schema_version (id, version) VALUES (1, ?)", (SCHEMA_VERSION,))
                elif version == 1:
                    for migration in (MIGRATION_2_SQL, MIGRATION_3_SQL, MIGRATION_4_SQL, MIGRATION_5_SQL, MIGRATION_6_SQL, MIGRATION_7_SQL, MIGRATION_8_SQL):
                        connection.executescript(migration)
                    connection.execute("UPDATE schema_version SET version = ?, applied_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = 1", (SCHEMA_VERSION,))
                elif version == 2:
                    for migration in (MIGRATION_3_SQL, MIGRATION_4_SQL, MIGRATION_5_SQL, MIGRATION_6_SQL, MIGRATION_7_SQL, MIGRATION_8_SQL):
                        connection.executescript(migration)
                    connection.execute("UPDATE schema_version SET version = ?, applied_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = 1", (SCHEMA_VERSION,))
                elif version == 3:
                    for migration in (MIGRATION_4_SQL, MIGRATION_5_SQL, MIGRATION_6_SQL, MIGRATION_7_SQL, MIGRATION_8_SQL):
                        connection.executescript(migration)
                    connection.execute("UPDATE schema_version SET version = ?, applied_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = 1", (SCHEMA_VERSION,))
                elif version == 4:
                    for migration in (MIGRATION_5_SQL, MIGRATION_6_SQL, MIGRATION_7_SQL, MIGRATION_8_SQL):
                        connection.executescript(migration)
                    connection.execute("UPDATE schema_version SET version = ?, applied_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = 1", (SCHEMA_VERSION,))
                elif version == 5:
                    for migration in (MIGRATION_6_SQL, MIGRATION_7_SQL, MIGRATION_8_SQL):
                        connection.executescript(migration)
                    connection.execute("UPDATE schema_version SET version = ?, applied_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = 1", (SCHEMA_VERSION,))
                elif version == 6:
                    for migration in (MIGRATION_7_SQL, MIGRATION_8_SQL):
                        connection.executescript(migration)
                    connection.execute("UPDATE schema_version SET version = ?, applied_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = 1", (SCHEMA_VERSION,))
                elif version == 7:
                    connection.executescript(MIGRATION_8_SQL)
                    connection.execute("UPDATE schema_version SET version = ?, applied_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = 1", (SCHEMA_VERSION,))
                else:
                    raise DatabaseError(f"unsupported schema version {version} (expected {SCHEMA_VERSION})")
        except sqlite3.Error as exc:
            raise DatabaseError(f"failed to initialize or migrate database: {exc}") from exc


@contextmanager
def database_transaction(path: Path | str) -> Iterator[sqlite3.Connection]:
    connection = connect_database(path)
    try:
        connection.execute("BEGIN")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
