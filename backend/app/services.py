"""Application services for S1B project and source operations."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import connect_database, database_transaction, initialize_database

MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
SUPPORTED_SUFFIXES = {".md", ".txt"}
JOB_STATUSES = {"draft", "scanning", "parsing", "review_input", "ready_for_evidence", "failed", "cancelled"}
SCENARIO_BOUNDARY_KINDS = {"normal", "ambiguous", "failure", "safety_boundary"}
EVALUATION_VERDICTS = {"pass", "partial", "fail", "not_run"}
QUALITY_RESULTS = {"pass", "warn", "fail"}


SOURCE_TYPES = {
    "research_paper", "book", "theory", "creator_content",
    "official_material", "case", "existing_skill", "other",
}


class ServiceError(ValueError):
    pass


class ProjectNotFound(ServiceError):
    pass


class DuplicateSource(ServiceError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_text(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    return normalized[1:] if normalized.startswith("\ufeff") else normalized

def _format_from_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".md", ".txt"}:
        raise ServiceError("只支持 Markdown（.md）或纯文本（.txt）文件")
    return suffix[1:]


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def create_project(db_path: Path | str, name: str, goal: str | None, description: str | None) -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise ServiceError("项目名称不能为空")
    initialize_database(db_path)
    project_id = str(uuid.uuid4())
    with database_transaction(db_path) as connection:
        connection.execute(
            "INSERT INTO projects (id, name, goal, description) VALUES (?, ?, ?, ?)",
            (project_id, name, goal, description),
        )
    return get_project(db_path, project_id)



def list_projects(db_path: Path | str) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        rows = connection.execute(
            "SELECT id, name, goal, description, schema_version, created_at, updated_at FROM projects ORDER BY updated_at DESC"
        ).fetchall()
        return [_row_dict(row) for row in rows]
def get_project(db_path: Path | str, project_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        project = connection.execute(
            "SELECT id, name, goal, description, schema_version, created_at, updated_at FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if project is None:
            raise ProjectNotFound("项目不存在")
        sources = connection.execute(
            """
            SELECT id, project_id, source_type, title, author_or_creator,
                   published_at, source_uri, original_path, notes, format,
                   snapshot_text, snapshot_sha256, original_file_sha256,
                   imported_at, created_at
            FROM sources WHERE project_id = ? ORDER BY created_at ASC
            """,
            (project_id,),
        ).fetchall()
        result = _row_dict(project)
        result["sources"] = []
        for source in sources:
            source_data = _row_dict(source)
            excerpt = connection.execute(
                """
                SELECT id, source_id, start_line, end_line, excerpt_text, created_at
                FROM excerpts WHERE source_id = ? ORDER BY start_line ASC LIMIT 1
                """,
                (source["id"],),
            ).fetchone()
            source_data["excerpt"] = _row_dict(excerpt) if excerpt else None
            result["sources"].append(source_data)
        return result


def import_source(
    db_path: Path | str,
    project_id: str,
    *,
    filename: str,
    content: str,
    title: str | None = None,
    source_type: str = "other",
    author_or_creator: str | None = None,
    published_at: str | None = None,
    source_uri: str | None = None,
    original_path: str | None = None,
    original_file_sha256: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    file_format = _format_from_filename(filename)
    if source_type not in SOURCE_TYPES:
        raise ServiceError("来源类型无效")
    snapshot_text = normalize_text(content)
    if not snapshot_text.strip():
        raise ServiceError("来源文件不能为空")
    source_title = (title or Path(filename).stem).strip()
    if not source_title:
        raise ServiceError("来源标题不能为空")
    snapshot_sha256 = hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest()
    lines = snapshot_text.splitlines()
    if not lines:
        raise ServiceError("来源文件不能为空")
    source_id = str(uuid.uuid4())
    excerpt_id = str(uuid.uuid4())
    initialize_database(db_path)
    try:
        with database_transaction(db_path) as connection:
            if connection.execute(
                "SELECT 1 FROM projects WHERE id = ?", (project_id,)
            ).fetchone() is None:
                raise ProjectNotFound("项目不存在")
            connection.execute(
                """
                INSERT INTO sources (
                    id, project_id, source_type, title, author_or_creator,
                    published_at, source_uri, original_path, notes, format,
                    snapshot_text, snapshot_sha256, original_file_sha256, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id, project_id, source_type, source_title,
                    author_or_creator, published_at, source_uri, original_path,
                    notes, file_format, snapshot_text, snapshot_sha256,
                    original_file_sha256, now_iso(),
                ),
            )
            connection.execute(
                """
                INSERT INTO excerpts (
                    id, source_id, start_line, end_line, excerpt_text
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (excerpt_id, source_id, 1, len(lines), snapshot_text),
            )
    except sqlite3.IntegrityError as exc:
        if "snapshot_sha256" in str(exc):
            raise DuplicateSource("该项目已经导入相同内容的来源") from exc
        raise
    project = get_project(db_path, project_id)
    return next(source for source in project["sources"] if source["id"] == source_id)



# S2A Job and local document parsing services

def _job_row(connection: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM distillation_jobs WHERE id = ?", (job_id,)
    ).fetchone()


def _job_payload(connection: sqlite3.Connection, job: sqlite3.Row) -> dict[str, Any]:
    documents = connection.execute(
        "SELECT * FROM documents WHERE job_id = ? ORDER BY relative_path ASC",
        (job["id"],),
    ).fetchall()
    events = connection.execute(
        "SELECT * FROM job_events WHERE job_id = ? ORDER BY created_at ASC",
        (job["id"],),
    ).fetchall()
    counts = {status: 0 for status in ("discovered", "parsed", "failed", "skipped")}
    for document in documents:
        counts[document["status"]] = counts.get(document["status"], 0) + 1
    payload = _row_dict(job)
    payload["input_manifest"] = json.loads(payload["input_manifest"] or "[]")
    payload["documents"] = []
    for document in documents:
        item = _row_dict(document)
        item.pop("pending_text", None)
        item.pop("pending_file_sha256", None)
        payload["documents"].append(item)
    payload["events"] = [_row_dict(event) for event in events]
    payload["document_counts"] = counts
    payload["manifest_count"] = len(payload["input_manifest"])
    return payload


def _job_event(connection: sqlite3.Connection, job_id: str, stage: str, status: str, message: str) -> None:
    connection.execute(
        "INSERT INTO job_events (id, job_id, stage, status, message) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), job_id, stage, status, message),
    )


def create_job(db_path: Path | str, project_id: str, name: str, goal: str | None, input_root: str) -> dict[str, Any]:
    name = name.strip()
    input_root = input_root.strip()
    if not name or not input_root:
        raise ServiceError("任务名称和输入路径不能为空")
    initialize_database(db_path)
    job_id = str(uuid.uuid4())
    with database_transaction(db_path) as connection:
        if connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
            raise ProjectNotFound("项目不存在")
        connection.execute(
            """
            INSERT INTO distillation_jobs (id, project_id, name, goal, status, current_stage, input_root)
            VALUES (?, ?, ?, ?, 'draft', 'scan', ?)
            """,
            (job_id, project_id, name, goal, input_root),
        )
        _job_event(connection, job_id, "job", "draft", "Job 已创建，等待扫描")
    return get_job(db_path, job_id)


def list_jobs(db_path: Path | str, project_id: str) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        rows = connection.execute(
            "SELECT * FROM distillation_jobs WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
        return [_job_payload(connection, row) for row in rows]


def get_job(db_path: Path | str, job_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        job = _job_row(connection, job_id)
        if job is None:
            raise ProjectNotFound("Job 不存在")
        return _job_payload(connection, job)


def _validate_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = Path(normalized)
    parts = normalized.split("/")
    if not normalized or normalized.startswith("/") or path.is_absolute() or any(part in {"", ".", ".."} for part in parts):
        raise ServiceError("文件相对路径无效或越界")
    if ":" in parts[0]:
        raise ServiceError("不允许绝对路径")
    return "/".join(parts)


def scan_job(db_path: Path | str, job_id: str, files: list[dict[str, Any]]) -> dict[str, Any]:
    initialize_database(db_path)
    if not isinstance(files, list) or len(files) > 500:
        raise ServiceError("单个任务最多选择 500 个文件")
    unsupported_count = 0
    manifest: list[dict[str, Any]] = []
    prepared: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    total_bytes = 0
    for item in files:
        if not isinstance(item, dict):
            raise ServiceError("文件清单格式无效")
        filename = str(item.get("filename", "")).strip()
        relative = _validate_relative_path(str(item.get("relative_path", filename)))
        suffix = Path(filename).suffix.lower()
        content_format = suffix[1:] if suffix in SUPPORTED_SUFFIXES else ""
        declared_format = str(item.get("format", content_format)).lower()
        if not filename or relative in seen_paths:
            raise ServiceError("文件名不能为空，且相对路径不能重复")
        seen_paths.add(relative)
        if not content_format or declared_format != content_format:
            unsupported_count += 1
            continue
        declared_size = int(item.get("size", len(str(item.get("content", "")).encode("utf-8"))))
        if declared_size < 0 or declared_size > MAX_DOCUMENT_BYTES:
            raise ServiceError(f"文件超过 5MB 限制：{filename}")
        total_bytes += declared_size
        if total_bytes > 25 * 1024 * 1024:
            raise ServiceError("单个 Job 的总输入不能超过 25MB")
        raw_error = item.get("error")
        error = str(raw_error).strip() if raw_error is not None else None
        error = error or None
        content = item.get("content")
        if content is not None and not isinstance(content, str):
            raise ServiceError(f"文件文本格式无效：{filename}")
        if content is not None and len(content.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise ServiceError(f"文件超过 5MB 限制：{filename}")
        if content is not None:
            declared_size = len(content.encode("utf-8"))
            total_bytes += max(0, declared_size - int(item.get("size", declared_size)))
            if total_bytes > 25 * 1024 * 1024:
                raise ServiceError("单个 Job 的总输入不能超过 25MB")
        manifest.append({"relative_path": relative, "filename": filename, "format": content_format, "size": declared_size, "original_file_sha256": item.get("original_file_sha256")})
        prepared.append({"relative_path": relative, "filename": filename, "format": content_format, "size": declared_size, "content": content, "error": error, "original_file_sha256": item.get("original_file_sha256")})

    with database_transaction(db_path) as connection:
        job = _job_row(connection, job_id)
        if job is None:
            raise ProjectNotFound("Job 不存在")
        existing_parsed = connection.execute("SELECT COUNT(*) FROM documents WHERE job_id = ? AND status = 'parsed'", (job_id,)).fetchone()[0]
        if existing_parsed:
            raise ServiceError("该 Job 已有已解析文档；重新运行请创建新 Job")
        connection.execute("DELETE FROM documents WHERE job_id = ?", (job_id,))
        for item in prepared:
            initial_status = "failed" if item["error"] or item["content"] is None else "discovered"
            connection.execute(
                """INSERT INTO documents (
                    id, job_id, relative_path, filename, format, file_size, status,
                    original_path, pending_text, pending_file_sha256, parse_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), job_id, item["relative_path"], item["filename"], item["format"], item["size"], initial_status, item["relative_path"], item["content"], item["original_file_sha256"], item["error"]),
            )
        if unsupported_count:
            _job_event(connection, job_id, "scan", "warning", f"跳过不支持格式 {unsupported_count} 个")
        if not prepared:
            error = f"没有找到支持的 Markdown/TXT 文件；不支持 {unsupported_count} 个文件"
            connection.execute("UPDATE distillation_jobs SET status = 'failed', current_stage = 'scan', input_manifest = ?, error_summary = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (json.dumps(manifest, ensure_ascii=False), error, job_id))
            _job_event(connection, job_id, "scan", "failed", error)
        else:
            failed = sum(1 for item in prepared if item["error"] or item["content"] is None)
            status = "review_input" if failed else "review_input"
            connection.execute("UPDATE distillation_jobs SET status = ?, current_stage = 'review_input', input_manifest = ?, error_summary = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (status, json.dumps(manifest, ensure_ascii=False), None if not failed else f"{failed} 个文件读取失败", job_id))
            _job_event(connection, job_id, "scan", "completed", f"接收 {len(prepared)} 个支持文件；跳过 {unsupported_count} 个不支持格式")
    payload = get_job(db_path, job_id)
    payload["unsupported_count"] = unsupported_count
    return payload


def _insert_or_reuse_source(connection: sqlite3.Connection, project_id: str, filename: str, text: str, original_path: str, file_hash: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    existing = connection.execute("SELECT id FROM sources WHERE project_id = ? AND snapshot_sha256 = ?", (project_id, digest)).fetchone()
    if existing:
        return existing[0]
    source_id = str(uuid.uuid4())
    connection.execute(
        """
        INSERT INTO sources (id, project_id, source_type, title, original_path, format, snapshot_text, snapshot_sha256, original_file_sha256, imported_at)
        VALUES (?, ?, 'other', ?, ?, ?, ?, ?, ?, ?)
        """,
        (source_id, project_id, Path(filename).stem, original_path, Path(filename).suffix.lower()[1:], text, digest, file_hash, now_iso()),
    )
    excerpt_id = str(uuid.uuid4())
    lines = text.splitlines()
    connection.execute("INSERT INTO excerpts (id, source_id, start_line, end_line, excerpt_text) VALUES (?, ?, 1, ?, ?)", (excerpt_id, source_id, len(lines), text))
    return source_id


def parse_job(db_path: Path | str, job_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    with database_transaction(db_path) as connection:
        job = _job_row(connection, job_id)
        if job is None:
            raise ProjectNotFound("Job 不存在")
        if job["status"] not in {"review_input", "parsing"}:
            raise ServiceError("Job 必须先完成输入扫描")
        connection.execute("UPDATE distillation_jobs SET status = 'parsing', current_stage = 'parse', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (job_id,))
        _job_event(connection, job_id, "parse", "started", "开始解析文件")
        documents = connection.execute("SELECT * FROM documents WHERE job_id = ? AND status = 'discovered' ORDER BY relative_path", (job_id,)).fetchall()
        for document in documents:
            try:
                text = document["pending_text"]
                if text is None:
                    raise ServiceError(document["parse_error"] or "浏览器未能读取文件文本")
                if len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
                    raise ServiceError("文件超过 5MB 限制")
                normalized = normalize_text(text)
                if not normalized.strip():
                    raise ServiceError("文件为空")
                digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                source_id = _insert_or_reuse_source(connection, job["project_id"], document["filename"], normalized, document["relative_path"], document["pending_file_sha256"] or digest)
                connection.execute("UPDATE documents SET source_id = ?, status = 'parsed', content_sha256 = ?, normalized_text = ?, pending_text = NULL, pending_file_sha256 = NULL, line_count = ?, title = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (source_id, digest, normalized, len(normalized.splitlines()), Path(document["filename"]).stem, document["id"]))
            except (UnicodeDecodeError, ServiceError) as exc:
                connection.execute("UPDATE documents SET status = 'failed', pending_text = NULL, pending_file_sha256 = NULL, parse_error = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (str(exc), document["id"]))
                _job_event(connection, job_id, "parse", "warning", f"{document['filename']}: {exc}")
        failed = connection.execute("SELECT COUNT(*) FROM documents WHERE job_id = ? AND status = 'failed'", (job_id,)).fetchone()[0]
        discovered = connection.execute("SELECT COUNT(*) FROM documents WHERE job_id = ? AND status = 'discovered'", (job_id,)).fetchone()[0]
        if failed or discovered:
            connection.execute("UPDATE distillation_jobs SET status = 'review_input', current_stage = 'review_input', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (job_id,))
            _job_event(connection, job_id, "parse", "failed", "存在解析失败或未处理文件")
        else:
            connection.execute("UPDATE distillation_jobs SET status = 'ready_for_evidence', current_stage = 'ready', completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (job_id,))
            _job_event(connection, job_id, "parse", "completed", "解析完成，输入可供 Evidence 阶段使用")
    return get_job(db_path, job_id)


def skip_failed_documents(db_path: Path | str, job_id: str, reason: str) -> dict[str, Any]:
    reason = reason.strip()
    if not reason:
        raise ServiceError("跳过失败文件必须填写理由")
    initialize_database(db_path)
    with database_transaction(db_path) as connection:
        job = _job_row(connection, job_id)
        if job is None:
            raise ProjectNotFound("Job 不存在")
        failed = connection.execute("SELECT COUNT(*) FROM documents WHERE job_id = ? AND status = 'failed'", (job_id,)).fetchone()[0]
        if not failed:
            raise ServiceError("当前没有可跳过的失败文件")
        connection.execute("UPDATE documents SET status = 'skipped', parse_error = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE job_id = ? AND status = 'failed'", (reason, job_id))
        connection.execute("UPDATE distillation_jobs SET status = 'ready_for_evidence', current_stage = 'ready', error_summary = ?, completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (f"用户跳过失败文件：{reason}", job_id))
        _job_event(connection, job_id, "review_input", "skipped", reason)
    return get_job(db_path, job_id)




EVIDENCE_TYPES = {"workflow_step", "decision_rule", "capability_hint", "terminology", "dependency", "exception", "quantitative_signal"}
EVIDENCE_LEVELS = {"A", "B", "C", "D", "unassessed"}
EVIDENCE_RELATIONS = {"direct_support", "context", "limitation", "counterexample"}
REVIEW_STATUSES = {"draft", "in_review", "approved", "rejected"}


def _evidence_payload(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    item = _row_dict(row)
    links = connection.execute(
        """
        SELECT ee.excerpt_id, ee.relation_kind, e.source_id, e.start_line, e.end_line,
               s.id AS source_id, s.title AS source_title, s.snapshot_sha256
        FROM evidence_excerpts ee
        JOIN excerpts e ON e.id = ee.excerpt_id
        JOIN sources s ON s.id = e.source_id
        WHERE ee.evidence_id = ?
        ORDER BY e.start_line
        """,
        (row["id"],),
    ).fetchall()
    item["excerpt_links"] = [_row_dict(link) for link in links]
    return item


def list_evidence(db_path: Path | str, job_id: str) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        if _job_row(connection, job_id) is None:
            raise ProjectNotFound("Job 不存在")
        rows = connection.execute("SELECT * FROM evidences WHERE job_id = ? ORDER BY created_at", (job_id,)).fetchall()
        return [_evidence_payload(connection, row) for row in rows]


def create_evidence(db_path: Path | str, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text", "")).strip()
    evidence_type = str(payload.get("evidence_type", ""))
    evidence_level = str(payload.get("evidence_level", "unassessed"))
    confidence = float(payload.get("confidence", 0))
    scope = str(payload.get("scope", "")).strip()
    limitations = str(payload.get("limitations", "")).strip()
    links = payload.get("excerpt_links") or []
    if not text or evidence_type not in EVIDENCE_TYPES or evidence_level not in EVIDENCE_LEVELS:
        raise ServiceError("Evidence 文本、类型或等级无效")
    if confidence < 0 or confidence > 1 or not scope or not limitations:
        raise ServiceError("Evidence 置信度、适用范围和限制必须有效")
    if not isinstance(links, list):
        raise ServiceError("Evidence 来源关联格式无效")
    evidence_id = str(uuid.uuid4())
    initialize_database(db_path)
    with database_transaction(db_path) as connection:
        job = _job_row(connection, job_id)
        if job is None:
            raise ProjectNotFound("Job 不存在")
        for link in links:
            excerpt_id = link.get("excerpt_id") if isinstance(link, dict) else None
            relation = link.get("relation_kind") if isinstance(link, dict) else None
            if not excerpt_id or relation not in EVIDENCE_RELATIONS:
                raise ServiceError("Evidence 来源关联无效")
            valid = connection.execute(
                """
                SELECT 1 FROM excerpts e
                JOIN sources s ON s.id = e.source_id
                WHERE e.id = ? AND s.project_id = ? AND EXISTS (SELECT 1 FROM documents d WHERE d.source_id = s.id AND d.job_id = ?)
                """, (excerpt_id, job["project_id"], job_id)
            ).fetchone()
            if valid is None:
                raise ServiceError("Evidence 只能绑定当前项目的来源摘录")
        connection.execute(
            """
            INSERT INTO evidences (id, job_id, text, evidence_type, evidence_level,
                confidence, scope, limitations, capability_hint, review_status,
                created_origin, review_note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, NULL)
            """,
            (evidence_id, job_id, text, evidence_type, evidence_level, confidence,
             scope, limitations, payload.get("capability_hint"), payload.get("created_origin", "manual")),
        )
        for link in links:
            connection.execute(
                "INSERT INTO evidence_excerpts (evidence_id, excerpt_id, relation_kind) VALUES (?, ?, ?)",
                (evidence_id, link["excerpt_id"], link["relation_kind"]),
            )
    with closing(connect_database(db_path)) as connection:
        row = connection.execute("SELECT * FROM evidences WHERE id = ?", (evidence_id,)).fetchone()
        return _evidence_payload(connection, row)


def review_evidence(db_path: Path | str, evidence_id: str, action: str, note: str | None = None) -> dict[str, Any]:
    if action not in {"approve", "reject", "in_review"}:
        raise ServiceError("审核动作无效")
    initialize_database(db_path)
    with database_transaction(db_path) as connection:
        row = connection.execute("SELECT * FROM evidences WHERE id = ?", (evidence_id,)).fetchone()
        if row is None:
            raise ProjectNotFound("Evidence 不存在")
        links = connection.execute("SELECT COUNT(*) FROM evidence_excerpts WHERE evidence_id = ?", (evidence_id,)).fetchone()[0]
        if action == "approve":
            if links < 1:
                raise ServiceError("Evidence 至少需要一个来源摘录才能批准")
            if not row["text"].strip() or not row["scope"].strip() or not row["limitations"].strip():
                raise ServiceError("Evidence 缺少文本、适用范围或限制")
        status = {"approve": "approved", "reject": "rejected", "in_review": "in_review"}[action]
        connection.execute(
            "UPDATE evidences SET review_status = ?, review_note = ?, approved_at = CASE WHEN ? = 'approved' THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NULL END, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (status, note, status, evidence_id),
        )
    with closing(connect_database(db_path)) as connection:
        return _evidence_payload(connection, connection.execute("SELECT * FROM evidences WHERE id = ?", (evidence_id,)).fetchone())


def evidence_source_context(db_path: Path | str, job_id: str, evidence_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        job = _job_row(connection, job_id)
        if job is None:
            raise ProjectNotFound("Job 不存在")
        evidence = connection.execute("SELECT * FROM evidences WHERE id=?", (evidence_id,)).fetchone()
        if evidence is None:
            raise ProjectNotFound("Evidence 不存在")
        if evidence["job_id"] != job_id:
            raise ServiceError("Evidence 不属于当前 Job")
        links = connection.execute(
            """
            SELECT ee.excerpt_id, ee.relation_kind, e.source_id, e.start_line, e.end_line,
                   e.excerpt_text, s.title AS source_title, s.original_path, s.format,
                   s.snapshot_sha256
            FROM evidence_excerpts ee
            JOIN excerpts e ON e.id=ee.excerpt_id
            JOIN sources s ON s.id=e.source_id
            WHERE ee.evidence_id=? AND s.project_id=?
            ORDER BY e.start_line, ee.relation_kind
            """,
            (evidence_id, job["project_id"]),
        ).fetchall()
        return {
            "evidence": {"id": evidence["id"], "text": evidence["text"], "review_status": evidence["review_status"]},
            "links": [_row_dict(link) for link in links],
        }


def evidence_source_map(db_path: Path | str, evidence_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        row = connection.execute("SELECT * FROM evidences WHERE id = ?", (evidence_id,)).fetchone()
        if row is None:
            raise ProjectNotFound("Evidence 不存在")
        item = _evidence_payload(connection, row)
        return {"evidence": {"id": item["id"], "text": item["text"], "review_status": item["review_status"]}, "links": item["excerpt_links"]}




CAPABILITY_STATUSES = {"candidate", "in_review", "approved", "rejected"}
PLAN_STATUSES = {"draft", "in_review", "approved", "rejected"}
PLAN_NODE_KINDS = {"instruction", "workflow_step", "decision_rule", "boundary", "reference", "script", "asset"}


def _capability_payload(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    item = _row_dict(row)
    evidence_rows = connection.execute(
        """
        SELECT e.id, e.text, e.evidence_type, e.evidence_level, e.confidence, e.review_status
        FROM capability_evidence ce JOIN evidences e ON e.id = ce.evidence_id
        WHERE ce.capability_id = ? ORDER BY e.created_at
        """, (row["id"],)
    ).fetchall()
    item["evidence"] = [_row_dict(e) for e in evidence_rows]
    item["evidence_ids"] = [e["id"] for e in evidence_rows]
    mechanisms = connection.execute("SELECT * FROM mechanisms WHERE capability_id = ? ORDER BY created_at", (row["id"],)).fetchall()
    item["mechanisms"] = []
    for mechanism in mechanisms:
        m = _row_dict(mechanism)
        m["evidence_ids"] = [r[0] for r in connection.execute("SELECT evidence_id FROM mechanism_evidence WHERE mechanism_id = ? ORDER BY evidence_id", (mechanism["id"],)).fetchall()]
        item["mechanisms"].append(m)
    return item


def list_capabilities(db_path: Path | str, job_id: str) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        if _job_row(connection, job_id) is None:
            raise ProjectNotFound("Job 不存在")
        rows = connection.execute("SELECT * FROM capabilities WHERE job_id = ? ORDER BY created_at", (job_id,)).fetchall()
        return [_capability_payload(connection, row) for row in rows]


def cluster_capabilities(db_path: Path | str, job_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    with database_transaction(db_path) as connection:
        if _job_row(connection, job_id) is None:
            raise ProjectNotFound("Job 不存在")
        evidence_rows = connection.execute(
            "SELECT * FROM evidences WHERE job_id = ? AND review_status = 'approved' ORDER BY created_at",
            (job_id,),
        ).fetchall()
        groups: dict[str, list[sqlite3.Row]] = {}
        for evidence in evidence_rows:
            label = (evidence["capability_hint"] or "").strip() or evidence["evidence_type"].replace("_", " ").title()
            groups.setdefault(label, []).append(evidence)
        created_ids: list[str] = []
        for name, group in groups.items():
            existing = connection.execute("SELECT * FROM capabilities WHERE job_id = ? AND name = ?", (job_id, name)).fetchone()
            if existing is None:
                capability_id = str(uuid.uuid4())
                connection.execute(
                    "INSERT INTO capabilities (id, job_id, name, summary, status) VALUES (?, ?, ?, ?, 'candidate')",
                    (capability_id, job_id, name, f"由 {len(group)} 条已批准 Evidence 形成的候选能力"),
                )
            else:
                capability_id = existing["id"]
                if existing["status"] != "candidate":
                    created_ids.append(capability_id)
                    continue
            for evidence in group:
                connection.execute("INSERT OR IGNORE INTO capability_evidence (capability_id, evidence_id) VALUES (?, ?)", (capability_id, evidence["id"]))
            created_ids.append(capability_id)
        _job_event(connection, job_id, "capability_cluster", "completed", f"按已批准 Evidence 生成/更新 {len(created_ids)} 个能力候选")
    return {"capabilities": list_capabilities(db_path, job_id), "created_or_updated": len(created_ids)}


def update_capability(db_path: Path | str, capability_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    initialize_database(db_path)
    with database_transaction(db_path) as connection:
        row = connection.execute("SELECT * FROM capabilities WHERE id = ?", (capability_id,)).fetchone()
        if row is None:
            raise ProjectNotFound("Capability 不存在")
        status = payload.get("status", row["status"])
        if status not in CAPABILITY_STATUSES:
            raise ServiceError("Capability 状态无效")
        name = str(payload.get("name", row["name"])).strip()
        if not name:
            raise ServiceError("Capability 名称不能为空")
        evidence_ids = payload.get("evidence_ids")
        if evidence_ids is not None:
            if status == "approved":
                raise ServiceError("已批准 Capability 不能直接改写证据集合；请重新打开审核")
            if not isinstance(evidence_ids, list) or not evidence_ids:
                raise ServiceError("Capability 至少需要一条 Evidence")
            for evidence_id in evidence_ids:
                supported = connection.execute("SELECT 1 FROM evidences WHERE id=? AND job_id=? AND review_status='approved'", (evidence_id, row["job_id"])).fetchone()
                if supported is None:
                    raise ServiceError("Capability 只能引用当前 Job 的已批准 Evidence")
            connection.execute("DELETE FROM capability_evidence WHERE capability_id=?", (capability_id,))
            for evidence_id in evidence_ids:
                connection.execute("INSERT INTO capability_evidence (capability_id, evidence_id) VALUES (?, ?)", (capability_id, evidence_id))
        connection.execute("UPDATE capabilities SET name = ?, summary = ?, status = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?", (name, payload.get("summary", row["summary"]), status, capability_id))
    with closing(connect_database(db_path)) as connection:
        return _capability_payload(connection, connection.execute("SELECT * FROM capabilities WHERE id = ?", (capability_id,)).fetchone())


def review_capability(db_path: Path | str, capability_id: str, action: str, note: str | None = None) -> dict[str, Any]:
    if action not in {"approve", "reject", "in_review"}:
        raise ServiceError("审核动作无效")
    initialize_database(db_path)
    with database_transaction(db_path) as connection:
        row = connection.execute("SELECT * FROM capabilities WHERE id = ?", (capability_id,)).fetchone()
        if row is None:
            raise ProjectNotFound("Capability 不存在")
        count = connection.execute("SELECT COUNT(*) FROM capability_evidence ce JOIN evidences e ON e.id = ce.evidence_id WHERE ce.capability_id = ? AND e.review_status = 'approved'", (capability_id,)).fetchone()[0]
        if action == "approve" and count < 1:
            raise ServiceError("Capability 至少需要一条已批准 Evidence")
        status = {"approve": "approved", "reject": "rejected", "in_review": "in_review"}[action]
        connection.execute("UPDATE capabilities SET status = ?, summary = CASE WHEN ? IS NULL THEN summary ELSE summary END, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?", (status, note, capability_id))
        _job_event(connection, row["job_id"], "capability_review", status, note or f"Capability {status}")
    with closing(connect_database(db_path)) as connection:
        return _capability_payload(connection, connection.execute("SELECT * FROM capabilities WHERE id = ?", (capability_id,)).fetchone())


def capability_source_map(db_path: Path | str, capability_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        row = connection.execute("SELECT * FROM capabilities WHERE id = ?", (capability_id,)).fetchone()
        if row is None:
            raise ProjectNotFound("Capability 不存在")
        item = _capability_payload(connection, row)
        links = connection.execute(
            """
            SELECT e.id AS id, e.id AS evidence_id, e.text, e.review_status, ee.relation_kind,
                   x.id AS excerpt_id, x.start_line, x.end_line, s.id AS source_id,
                   s.title AS source_title, s.snapshot_sha256
            FROM capability_evidence ce JOIN evidences e ON e.id=ce.evidence_id
            JOIN evidence_excerpts ee ON ee.evidence_id=e.id
            JOIN excerpts x ON x.id=ee.excerpt_id JOIN sources s ON s.id=x.source_id
            WHERE ce.capability_id=? ORDER BY e.created_at, x.start_line
            """, (capability_id,)
        ).fetchall()
        return {"capability": {"id": item["id"], "name": item["name"], "status": item["status"]}, "evidence": [_row_dict(link) for link in links]}


def create_mechanism(db_path: Path | str, capability_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    description = str(payload.get("description", "")).strip()
    scope = str(payload.get("scope", "")).strip()
    limitations = str(payload.get("limitations", "")).strip()
    evidence_ids = payload.get("evidence_ids") or []
    if not name or not description or not scope or not limitations or not isinstance(evidence_ids, list) or not evidence_ids:
        raise ServiceError("Mechanism 必须包含名称、描述、范围、限制和 Evidence 支撑")
    initialize_database(db_path)
    mechanism_id = str(uuid.uuid4())
    with database_transaction(db_path) as connection:
        capability = connection.execute("SELECT * FROM capabilities WHERE id = ?", (capability_id,)).fetchone()
        if capability is None:
            raise ProjectNotFound("Capability 不存在")
        for evidence_id in evidence_ids:
            supported = connection.execute("SELECT 1 FROM capability_evidence ce JOIN evidences e ON e.id=ce.evidence_id WHERE ce.capability_id=? AND e.id=? AND e.review_status='approved'", (capability_id, evidence_id)).fetchone()
            if supported is None:
                raise ServiceError("Mechanism 只能引用当前 Capability 下已批准的 Evidence")
        connection.execute("INSERT INTO mechanisms (id, capability_id, name, description, scope, limitations, status) VALUES (?, ?, ?, ?, ?, ?, 'draft')", (mechanism_id, capability_id, name, description, scope, limitations))
        for evidence_id in evidence_ids:
            connection.execute("INSERT INTO mechanism_evidence (mechanism_id, evidence_id) VALUES (?, ?)", (mechanism_id, evidence_id))
    return get_mechanism(db_path, mechanism_id)


def get_mechanism(db_path: Path | str, mechanism_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        row = connection.execute("SELECT * FROM mechanisms WHERE id=?", (mechanism_id,)).fetchone()
        if row is None:
            raise ProjectNotFound("Mechanism 不存在")
        item = _row_dict(row)
        item["evidence_ids"] = [r[0] for r in connection.execute("SELECT evidence_id FROM mechanism_evidence WHERE mechanism_id=? ORDER BY evidence_id", (mechanism_id,)).fetchall()]
        return item


def review_mechanism(db_path: Path | str, mechanism_id: str, action: str, note: str | None = None) -> dict[str, Any]:
    if action not in {"approve", "reject", "in_review"}:
        raise ServiceError("审核动作无效")
    initialize_database(db_path)
    with database_transaction(db_path) as connection:
        row = connection.execute("SELECT m.*, c.job_id, c.status AS capability_status FROM mechanisms m JOIN capabilities c ON c.id=m.capability_id WHERE m.id=?", (mechanism_id,)).fetchone()
        if row is None:
            raise ProjectNotFound("Mechanism 不存在")
        count = connection.execute("SELECT COUNT(*) FROM mechanism_evidence me JOIN evidences e ON e.id=me.evidence_id WHERE me.mechanism_id=? AND e.review_status='approved'", (mechanism_id,)).fetchone()[0]
        if action == "approve" and (count < 1 or row["capability_status"] != "approved"):
            raise ServiceError("Mechanism 需要至少一条已批准 Evidence，且所属 Capability 必须已批准")
        status = {"approve":"approved", "reject":"rejected", "in_review":"in_review"}[action]
        connection.execute("UPDATE mechanisms SET status=?, review_note=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (status, note, mechanism_id))
    return get_mechanism(db_path, mechanism_id)


def create_capability(db_path: Path | str, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    summary = str(payload.get("summary", ""))
    evidence_ids = payload.get("evidence_ids") or []
    if not name or not isinstance(evidence_ids, list) or not evidence_ids:
        raise ServiceError("Capability 名称和 Evidence 支撑不能为空")
    initialize_database(db_path)
    capability_id = str(uuid.uuid4())
    with database_transaction(db_path) as connection:
        if _job_row(connection, job_id) is None:
            raise ProjectNotFound("Job 不存在")
        for evidence_id in evidence_ids:
            row = connection.execute("SELECT 1 FROM evidences WHERE id=? AND job_id=? AND review_status='approved'", (evidence_id, job_id)).fetchone()
            if row is None:
                raise ServiceError("Capability 只能引用当前 Job 的已批准 Evidence")
        connection.execute("INSERT INTO capabilities (id, job_id, name, summary, status) VALUES (?, ?, ?, ?, 'candidate')", (capability_id, job_id, name, summary))
        for evidence_id in evidence_ids:
            connection.execute("INSERT INTO capability_evidence (capability_id,evidence_id) VALUES (?,?)", (capability_id,evidence_id))
    with closing(connect_database(db_path)) as connection:
        return _capability_payload(connection, connection.execute("SELECT * FROM capabilities WHERE id=?", (capability_id,)).fetchone())


def merge_capabilities(db_path: Path | str, job_id: str, capability_ids: list[str], name: str, summary: str = "") -> dict[str, Any]:
    if not isinstance(capability_ids, list) or len(capability_ids) < 2 or not name.strip():
        raise ServiceError("合并至少需要两个 Capability 和一个名称")
    initialize_database(db_path)
    merged_id = str(uuid.uuid4())
    with database_transaction(db_path) as connection:
        placeholders = ",".join("?" for _ in capability_ids)
        rows = connection.execute(f"SELECT * FROM capabilities WHERE job_id=? AND id IN ({placeholders})", [job_id, *capability_ids]).fetchall()
        if len(rows) != len(set(capability_ids)):
            raise ServiceError("待合并 Capability 必须属于当前 Job")
        if any(row["status"] == "approved" for row in rows):
            raise ServiceError("已批准 Capability 不能直接合并；请先重新打开审核")
        connection.execute("INSERT INTO capabilities (id, job_id, name, summary, status) VALUES (?, ?, ?, ?, 'candidate')", (merged_id, job_id, name.strip(), summary))
        evidence_ids = set()
        for capability_id in capability_ids:
            evidence_ids.update(r[0] for r in connection.execute("SELECT evidence_id FROM capability_evidence WHERE capability_id=?", (capability_id,)).fetchall())
            connection.execute("UPDATE mechanisms SET capability_id=? WHERE capability_id=?", (merged_id, capability_id))
            connection.execute("UPDATE capabilities SET status='rejected', summary='已合并到另一个 Capability', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (capability_id,))
        for evidence_id in sorted(evidence_ids):
            connection.execute("INSERT INTO capability_evidence (capability_id,evidence_id) VALUES (?,?)", (merged_id,evidence_id))
    with closing(connect_database(db_path)) as connection:
        return _capability_payload(connection, connection.execute("SELECT * FROM capabilities WHERE id=?", (merged_id,)).fetchone())


def create_skill_plan(db_path: Path | str, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    capability_ids = payload.get("capability_ids") or []
    mechanism_ids = payload.get("mechanism_ids") or []
    nodes = payload.get("nodes") or []
    if not name or not isinstance(capability_ids, list) or not isinstance(mechanism_ids, list) or not isinstance(nodes, list):
        raise ServiceError("SkillPlan 名称、能力关联或节点格式无效")
    initialize_database(db_path)
    plan_id = str(uuid.uuid4())
    with database_transaction(db_path) as connection:
        if _job_row(connection, job_id) is None:
            raise ProjectNotFound("Job 不存在")
        for capability_id in capability_ids:
            item = connection.execute("SELECT job_id FROM capabilities WHERE id=?", (capability_id,)).fetchone()
            if item is None or item["job_id"] != job_id:
                raise ServiceError("SkillPlan 只能引用当前 Job 的 Capability")
        connection.execute("INSERT INTO skill_plans (id, job_id, name, description, status) VALUES (?, ?, ?, ?, 'draft')", (plan_id, job_id, name, payload.get("description", "")))
        for capability_id in capability_ids:
            connection.execute("INSERT INTO skill_plan_capabilities (skill_plan_id, capability_id) VALUES (?, ?)", (plan_id, capability_id))
        for mechanism_id in mechanism_ids:
            connection.execute("INSERT INTO skill_plan_mechanisms (skill_plan_id, mechanism_id) VALUES (?, ?)", (plan_id, mechanism_id))
        for index, node in enumerate(nodes):
            kind = node.get("node_kind")
            title = str(node.get("title", "")).strip()
            content = str(node.get("content", "")).strip()
            if kind not in PLAN_NODE_KINDS or not title or not content:
                raise ServiceError("SkillPlan 节点类型、标题或内容无效")
            order_index = node.get("order_index")
            if order_index is None:
                order_index = index
            connection.execute("INSERT INTO skill_plan_nodes (id, skill_plan_id, node_kind, title, content, order_index) VALUES (?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), plan_id, kind, title, content, int(order_index)))
    return get_skill_plan(db_path, plan_id)


def list_skill_plans(db_path: Path | str, job_id: str) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        if _job_row(connection, job_id) is None:
            raise ProjectNotFound("Job 不存在")
        ids = [row[0] for row in connection.execute("SELECT id FROM skill_plans WHERE job_id=? ORDER BY created_at", (job_id,)).fetchall()]
    return [get_skill_plan(db_path, plan_id) for plan_id in ids]


def get_skill_plan(db_path: Path | str, plan_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        plan = connection.execute("SELECT * FROM skill_plans WHERE id=?", (plan_id,)).fetchone()
        if plan is None:
            raise ProjectNotFound("SkillPlan 不存在")
        item = _row_dict(plan)
        item["capabilities"] = [ _capability_payload(connection, c) for c in connection.execute("SELECT c.* FROM capabilities c JOIN skill_plan_capabilities spc ON spc.capability_id=c.id WHERE spc.skill_plan_id=?", (plan_id,)).fetchall() ]
        item["mechanisms"] = [_row_dict(m) for m in connection.execute("SELECT m.* FROM mechanisms m JOIN skill_plan_mechanisms spm ON spm.mechanism_id=m.id WHERE spm.skill_plan_id=?", (plan_id,)).fetchall()]
        item["nodes"] = []
        for node in connection.execute("SELECT * FROM skill_plan_nodes WHERE skill_plan_id=? ORDER BY order_index", (plan_id,)).fetchall():
            n = _row_dict(node)
            n["evidence_ids"] = [r[0] for r in connection.execute("SELECT evidence_id FROM skill_plan_node_evidence WHERE node_id=? ORDER BY evidence_id", (node["id"],)).fetchall()]
            item["nodes"].append(n)
        return item


def set_skill_plan_node_evidence(db_path: Path | str, plan_id: str, node_index: int, evidence_ids: list[str]) -> dict[str, Any]:
    if not isinstance(evidence_ids, list) or not evidence_ids:
        raise ServiceError("每个 SkillPlan 节点至少需要一条 Evidence source-map")
    initialize_database(db_path)
    with database_transaction(db_path) as connection:
        plan = connection.execute("SELECT * FROM skill_plans WHERE id=?", (plan_id,)).fetchone()
        if plan is None:
            raise ProjectNotFound("SkillPlan 不存在")
        node = connection.execute("SELECT * FROM skill_plan_nodes WHERE skill_plan_id=? AND order_index=?", (plan_id, node_index)).fetchone()
        if node is None:
            raise ProjectNotFound("SkillPlan 节点不存在")
        for evidence_id in evidence_ids:
            valid = connection.execute("SELECT 1 FROM evidences WHERE id=? AND job_id=? AND review_status='approved'", (evidence_id, plan["job_id"])).fetchone()
            if valid is None:
                raise ServiceError("节点只能映射到当前 Job 的已批准 Evidence")
        connection.execute("DELETE FROM skill_plan_node_evidence WHERE node_id=?", (node["id"],))
        for evidence_id in evidence_ids:
            connection.execute("INSERT INTO skill_plan_node_evidence (node_id,evidence_id) VALUES (?,?)", (node["id"], evidence_id))
    return get_skill_plan(db_path, plan_id)


def review_skill_plan(db_path: Path | str, plan_id: str, action: str, note: str | None = None) -> dict[str, Any]:
    if action not in {"approve", "reject", "in_review"}:
        raise ServiceError("审核动作无效")
    initialize_database(db_path)
    with database_transaction(db_path) as connection:
        plan = connection.execute("SELECT * FROM skill_plans WHERE id=?", (plan_id,)).fetchone()
        if plan is None:
            raise ProjectNotFound("SkillPlan 不存在")
        capability_rows = connection.execute("SELECT c.status FROM skill_plan_capabilities spc JOIN capabilities c ON c.id=spc.capability_id WHERE spc.skill_plan_id=?", (plan_id,)).fetchall()
        mechanisms = connection.execute("SELECT m.status FROM mechanisms m JOIN skill_plan_mechanisms spm ON spm.mechanism_id=m.id WHERE spm.skill_plan_id=?", (plan_id,)).fetchall()
        nodes = connection.execute("SELECT * FROM skill_plan_nodes WHERE skill_plan_id=?", (plan_id,)).fetchall()
        if action == "approve":
            if not capability_rows or any(row["status"] != "approved" for row in capability_rows):
                raise ServiceError("SkillPlan 只能引用已批准 Capability")
            if any(mechanism["status"] != "approved" for mechanism in mechanisms):
                raise ServiceError("SkillPlan 只能引用已批准 Mechanism")
            if not nodes:
                raise ServiceError("SkillPlan 至少需要一个节点")
            for node in nodes:
                supported = connection.execute("SELECT COUNT(*) FROM skill_plan_node_evidence ne JOIN evidences e ON e.id=ne.evidence_id WHERE ne.node_id=? AND e.review_status='approved'", (node["id"],)).fetchone()[0]
                if supported < 1:
                    raise ServiceError("每个 SkillPlan 节点都必须映射到已批准 Evidence")
        status = {"approve":"approved","reject":"rejected","in_review":"in_review"}[action]
        connection.execute("UPDATE skill_plans SET status=?, review_note=?, approved_at=CASE WHEN ?='approved' THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NULL END, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (status,note,status,plan_id))
    return get_skill_plan(db_path, plan_id)


def skill_plan_source_map(db_path: Path | str, plan_id: str) -> dict[str, Any]:
    plan = get_skill_plan(db_path, plan_id)
    result = []
    for node in plan["nodes"]:
        source_links = []
        for evidence_id in node["evidence_ids"]:
            source_links.extend(evidence_source_map(db_path, evidence_id)["links"])
        result.append({"node_id": node["id"], "title": node["title"], "evidence_ids": node["evidence_ids"], "sources": source_links})
    return {"skill_plan_id": plan_id, "nodes": result}


# S4 Skill Compiler and export services

def _safe_export_path(value: str) -> Path:
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raise ServiceError("导出目录必须是绝对路径")
    if any(part in {".", ".."} for part in raw.parts):
        raise ServiceError("导出路径包含非法路径段")
    return raw


def _approved_plan_for_compile(connection: sqlite3.Connection, plan_id: str) -> sqlite3.Row:
    plan = connection.execute("SELECT * FROM skill_plans WHERE id=?", (plan_id,)).fetchone()
    if plan is None:
        raise ProjectNotFound("SkillPlan 不存在")
    if plan["status"] != "approved":
        raise ServiceError("只有 approved SkillPlan 才能编译")
    capabilities = connection.execute("SELECT c.* FROM capabilities c JOIN skill_plan_capabilities spc ON spc.capability_id=c.id WHERE spc.skill_plan_id=?", (plan_id,)).fetchall()
    if not capabilities or any(item["status"] != "approved" for item in capabilities):
        raise ServiceError("SkillPlan 引用的 Capability 尚未全部批准")
    mechanisms = connection.execute("SELECT m.* FROM mechanisms m JOIN skill_plan_mechanisms spm ON spm.mechanism_id=m.id WHERE spm.skill_plan_id=?", (plan_id,)).fetchall()
    if any(item["status"] != "approved" for item in mechanisms):
        raise ServiceError("SkillPlan 引用的 Mechanism 尚未全部批准")
    nodes = connection.execute("SELECT * FROM skill_plan_nodes WHERE skill_plan_id=? ORDER BY order_index", (plan_id,)).fetchall()
    if not nodes:
        raise ServiceError("SkillPlan 没有可编译节点")
    for node in nodes:
        count = connection.execute("SELECT COUNT(*) FROM skill_plan_node_evidence ne JOIN evidences e ON e.id=ne.evidence_id WHERE ne.node_id=? AND e.review_status='approved'", (node["id"],)).fetchone()[0]
        if count < 1:
            raise ServiceError(f"SkillPlan 节点缺少 approved source-map：{node['title']}")
    return plan


def compile_skill_preview(db_path: Path | str, plan_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        plan = _approved_plan_for_compile(connection, plan_id)
        nodes = connection.execute("SELECT * FROM skill_plan_nodes WHERE skill_plan_id=? ORDER BY order_index", (plan_id,)).fetchall()
        capability_names = [row[0] for row in connection.execute("SELECT c.name FROM capabilities c JOIN skill_plan_capabilities spc ON spc.capability_id=c.id WHERE spc.skill_plan_id=? ORDER BY c.name", (plan_id,)).fetchall()]
        files: list[dict[str, Any]] = []
        skill_lines = [f"# {plan['name']}", "", plan["description"] or "", "", "## Workflow", ""]
        source_map: dict[str, Any] = {}
        for node in nodes:
            skill_lines.extend([f"### {node['title']}", node["content"], ""])
            evidence_ids = [row[0] for row in connection.execute("SELECT evidence_id FROM skill_plan_node_evidence WHERE node_id=? ORDER BY evidence_id", (node["id"],)).fetchall()]
            source_map[f"SKILL.md#{node['id']}"] = {"node_id": node["id"], "evidence_ids": evidence_ids}
        skill_content = "\n".join(skill_lines).strip() + "\n"
        files.append({"path": "SKILL.md", "content": skill_content, "sha256": hashlib.sha256(skill_content.encode("utf-8")).hexdigest(), "source_keys": list(source_map)})
        references = "# Capability Sources\n\n" + "\n".join(f"- {name}" for name in capability_names) + "\n"
        source_map["references/capabilities.md"] = {"capabilities": capability_names}
        files.append({"path": "references/capabilities.md", "content": references, "sha256": hashlib.sha256(references.encode("utf-8")).hexdigest(), "source_keys": ["references/capabilities.md"]})
        generated_id = str(uuid.uuid4())
        connection.execute("INSERT INTO generated_skills (id, skill_plan_id, status, file_manifest, source_map) VALUES (?, ?, 'preview', ?, ?)", (generated_id, plan_id, json.dumps(files, ensure_ascii=False), json.dumps(source_map, ensure_ascii=False)))
        connection.commit()
        return {"id": generated_id, "skill_plan_id": plan_id, "status": "preview", "files": files, "source_map": source_map}


def _generated_payload(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    item = _row_dict(row)
    manifest = _json_loads(item.get("file_manifest"), [])
    item["files"] = manifest if isinstance(manifest, list) else []
    item["source_map"] = _json_loads(item.get("source_map"), {})
    item.pop("file_manifest", None)
    return item


def list_generated_skills(db_path: Path | str, plan_id: str) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        if connection.execute("SELECT 1 FROM skill_plans WHERE id=?", (plan_id,)).fetchone() is None:
            raise ProjectNotFound("SkillPlan 不存在")
        rows = connection.execute("SELECT * FROM generated_skills WHERE skill_plan_id=? ORDER BY created_at DESC", (plan_id,)).fetchall()
        return [_generated_payload(connection, row) for row in rows]


def get_generated_skill(db_path: Path | str, generated_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        row = _generated_row(connection, generated_id)
        if row is None:
            raise ProjectNotFound("GeneratedSkill 不存在")
        return _generated_payload(connection, row)


def export_generated_skill(db_path: Path | str, generated_id: str, output_path: str, overwrite: bool, confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise ServiceError("导出需要明确 confirm=true")
    target = _safe_export_path(output_path)
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        generated = connection.execute("SELECT * FROM generated_skills WHERE id=?", (generated_id,)).fetchone()
        if generated is None:
            raise ProjectNotFound("GeneratedSkill 不存在")
        plan = _approved_plan_for_compile(connection, generated["skill_plan_id"])
    preview = compile_skill_preview(db_path, generated["skill_plan_id"])
    if target.exists() and not overwrite:
        raise ServiceError("目标目录已存在，必须明确 overwrite=true 才能覆盖")
    temp = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    try:
        temp.mkdir(parents=True, exist_ok=False)
        for file in preview["files"]:
            path = temp / file["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(file["content"], encoding="utf-8")
        source_map_path = temp / "references" / "source-map.json"
        source_map_path.parent.mkdir(parents=True, exist_ok=True)
        source_map_path.write_text(json.dumps(preview["source_map"], ensure_ascii=False, indent=2), encoding="utf-8")
        if target.exists():
            import shutil
            shutil.rmtree(target)
        temp.replace(target)
        output_hash = hashlib.sha256("".join(file["sha256"] for file in preview["files"]).encode("utf-8")).hexdigest()
        with database_transaction(db_path) as connection:
            connection.execute("UPDATE generated_skills SET status='exported', file_manifest=?, source_map=? WHERE id=?", (json.dumps(preview["files"], ensure_ascii=False), json.dumps(preview["source_map"], ensure_ascii=False), generated_id))
            project_id = connection.execute("SELECT project_id FROM distillation_jobs WHERE id = (SELECT job_id FROM skill_plans WHERE id=?)", (generated["skill_plan_id"],)).fetchone()[0]
            run_id = str(uuid.uuid4())
            connection.execute("INSERT INTO export_runs (id, project_id, skill_plan_id, output_path, output_sha256, status, scope_json) VALUES (?, ?, ?, ?, ?, 'exported', ?)", (run_id, project_id, generated["skill_plan_id"], str(target), output_hash, json.dumps({"overwrite": overwrite, "files": [file["path"] for file in preview["files"]]}, ensure_ascii=False)))
        return {"id": generated_id, "run_id": run_id, "status": "exported", "output_path": str(target), "files": [file["path"] for file in preview["files"]] + ["references/source-map.json"]}
    except Exception:
        import shutil
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)
        raise

# S5 Scenario evaluation and quality-loop services

def _json_loads(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


def _generated_row(connection: sqlite3.Connection, generated_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM generated_skills WHERE id=?", (generated_id,)).fetchone()


def _plan_version_fingerprint(connection: sqlite3.Connection, plan_id: str) -> str:
    plan = connection.execute("SELECT * FROM skill_plans WHERE id=?", (plan_id,)).fetchone()
    if plan is None:
        raise ProjectNotFound("SkillPlan 不存在")
    nodes = []
    for node in connection.execute("SELECT * FROM skill_plan_nodes WHERE skill_plan_id=? ORDER BY order_index", (plan_id,)).fetchall():
        nodes.append({
            "id": node["id"],
            "node_kind": node["node_kind"],
            "title": node["title"],
            "content": node["content"],
            "order_index": node["order_index"],
            "evidence_ids": [row[0] for row in connection.execute("SELECT evidence_id FROM skill_plan_node_evidence WHERE node_id=? ORDER BY evidence_id", (node["id"],)).fetchall()],
        })
    payload = {
        "skill_plan_id": plan_id,
        "status": plan["status"],
        "approved_at": plan["approved_at"],
        "updated_at": plan["updated_at"],
        "nodes": nodes,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _generated_version_fingerprint(connection: sqlite3.Connection, generated: sqlite3.Row) -> str:
    payload = {
        "generated_skill_id": generated["id"],
        "skill_plan_id": generated["skill_plan_id"],
        "status": generated["status"],
        "created_at": generated["created_at"],
        "file_manifest": _json_loads(generated["file_manifest"], []),
        "source_map": _json_loads(generated["source_map"], {}),
        "plan_fingerprint": _plan_version_fingerprint(connection, generated["skill_plan_id"]),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _scenario_payload(row: sqlite3.Row) -> dict[str, Any]:
    return _row_dict(row)


def _evaluation_payload(row: sqlite3.Row) -> dict[str, Any]:
    return _row_dict(row)


def create_scenario(db_path: Path | str, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title", "")).strip()
    input_text = str(payload.get("input_text", "")).strip()
    boundary_kind = str(payload.get("boundary_kind", "")).strip()
    expected_behavior = str(payload.get("expected_behavior", "")).strip()
    forbidden_behavior = str(payload.get("forbidden_behavior", "")).strip()
    generated_skill_id = payload.get("generated_skill_id") or None
    if not title or not input_text or not expected_behavior or not forbidden_behavior:
        raise ServiceError("Scenario 标题、输入、期望行为和禁止行为不能为空")
    if boundary_kind not in SCENARIO_BOUNDARY_KINDS:
        raise ServiceError("Scenario boundary_kind 无效")
    initialize_database(db_path)
    scenario_id = str(uuid.uuid4())
    with database_transaction(db_path) as connection:
        plan = connection.execute("SELECT * FROM skill_plans WHERE id=?", (plan_id,)).fetchone()
        if plan is None:
            raise ProjectNotFound("SkillPlan 不存在")
        if plan["status"] != "approved":
            raise ServiceError("Scenario 只能绑定 approved SkillPlan")
        if generated_skill_id:
            generated = _generated_row(connection, str(generated_skill_id))
            if generated is None:
                raise ProjectNotFound("GeneratedSkill 不存在")
            if generated["skill_plan_id"] != plan_id:
                raise ServiceError("Scenario 只能绑定同一 SkillPlan 的 GeneratedSkill")
            version_fingerprint = _generated_version_fingerprint(connection, generated)
        else:
            version_fingerprint = _plan_version_fingerprint(connection, plan_id)
        connection.execute(
            """
            INSERT INTO scenarios (id, skill_plan_id, generated_skill_id, title, input_text,
                boundary_kind, expected_behavior, forbidden_behavior, version_fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (scenario_id, plan_id, generated_skill_id, title, input_text, boundary_kind, expected_behavior, forbidden_behavior, version_fingerprint),
        )
    with closing(connect_database(db_path)) as connection:
        return _scenario_payload(connection.execute("SELECT * FROM scenarios WHERE id=?", (scenario_id,)).fetchone())


def list_scenarios(db_path: Path | str, plan_id: str) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        if connection.execute("SELECT 1 FROM skill_plans WHERE id=?", (plan_id,)).fetchone() is None:
            raise ProjectNotFound("SkillPlan 不存在")
        rows = connection.execute("SELECT * FROM scenarios WHERE skill_plan_id=? ORDER BY created_at, title", (plan_id,)).fetchall()
        return [_scenario_payload(row) for row in rows]


def create_evaluation(db_path: Path | str, scenario_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    observed_behavior = str(payload.get("observed_behavior", "")).strip()
    verdict = str(payload.get("verdict", "")).strip()
    notes = str(payload.get("notes", "") or "").strip()
    evaluator = str(payload.get("evaluator", "manual") or "manual").strip()
    if not observed_behavior:
        raise ServiceError("Evaluation observed_behavior 不能为空")
    if verdict not in EVALUATION_VERDICTS:
        raise ServiceError("Evaluation verdict 无效")
    if not evaluator:
        evaluator = "manual"
    initialize_database(db_path)
    evaluation_id = str(uuid.uuid4())
    with database_transaction(db_path) as connection:
        scenario = connection.execute("SELECT * FROM scenarios WHERE id=?", (scenario_id,)).fetchone()
        if scenario is None:
            raise ProjectNotFound("Scenario 不存在")
        connection.execute(
            """
            INSERT INTO evaluations (id, scenario_id, skill_plan_id, generated_skill_id,
                observed_behavior, verdict, notes, evaluator, version_fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (evaluation_id, scenario_id, scenario["skill_plan_id"], scenario["generated_skill_id"], observed_behavior, verdict, notes, evaluator, scenario["version_fingerprint"]),
        )
    with closing(connect_database(db_path)) as connection:
        return _evaluation_payload(connection.execute("SELECT * FROM evaluations WHERE id=?", (evaluation_id,)).fetchone())


def list_evaluations(db_path: Path | str, plan_id: str) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        if connection.execute("SELECT 1 FROM skill_plans WHERE id=?", (plan_id,)).fetchone() is None:
            raise ProjectNotFound("SkillPlan 不存在")
        rows = connection.execute(
            """
            SELECT e.*, s.title AS scenario_title, s.boundary_kind
            FROM evaluations e
            JOIN scenarios s ON s.id=e.scenario_id
            WHERE e.skill_plan_id=?
            ORDER BY e.evaluated_at DESC
            """,
            (plan_id,),
        ).fetchall()
        return [_evaluation_payload(row) for row in rows]


def _quality_result_summary(results: list[str]) -> str:
    if "fail" in results:
        return "blocked"
    if "warn" in results:
        return "needs_revision"
    return "pass"


def _result_from_messages(failures: list[str], warnings: list[str]) -> str:
    if failures:
        return "fail"
    if warnings:
        return "warn"
    return "pass"


def _scan_license_privacy_text(text: str) -> tuple[list[str], list[str]]:
    lowered = text.lower()
    failures: list[str] = []
    warnings: list[str] = []
    if "begin private key" in lowered or "api_key" in lowered or "password=" in lowered or "sk-" in text:
        failures.append("发现疑似密钥或私密凭证")
    if "c:\\users\\" in lowered or "/users/" in lowered or "/home/" in lowered:
        failures.append("发现疑似本机私密路径")
    if "完整转载" in text or "全文复制" in text:
        warnings.append("发现疑似大段受限原文复制提示")
    return failures, warnings


def run_quality_check(db_path: Path | str, generated_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    report_id = str(uuid.uuid4())
    with database_transaction(db_path) as connection:
        generated = _generated_row(connection, generated_id)
        if generated is None:
            raise ProjectNotFound("GeneratedSkill 不存在")
        plan = connection.execute("SELECT * FROM skill_plans WHERE id=?", (generated["skill_plan_id"],)).fetchone()
        if plan is None:
            raise ProjectNotFound("SkillPlan 不存在")
        manifest = _json_loads(generated["file_manifest"], [])
        source_map = _json_loads(generated["source_map"], {})
        version_fingerprint = _generated_version_fingerprint(connection, generated)

        trace_failures: list[str] = []
        trace_warnings: list[str] = []
        if not isinstance(source_map, dict) or not source_map:
            trace_failures.append("GeneratedSkill 缺少 source-map")
        else:
            node_keys = [key for key, value in source_map.items() if isinstance(value, dict) and "node_id" in value]
            if not node_keys:
                trace_failures.append("source-map 没有任何 SkillPlan 节点映射")
            for key in node_keys:
                evidence_ids = source_map.get(key, {}).get("evidence_ids", [])
                if not evidence_ids:
                    trace_failures.append(f"{key} 缺少 Evidence 映射")
                for evidence_id in evidence_ids:
                    approved = connection.execute("SELECT 1 FROM evidences WHERE id=? AND review_status='approved'", (evidence_id,)).fetchone()
                    if approved is None:
                        trace_failures.append(f"{key} 引用了未批准或不存在的 Evidence")

        nodes = connection.execute("SELECT * FROM skill_plan_nodes WHERE skill_plan_id=? ORDER BY order_index", (generated["skill_plan_id"],)).fetchall()
        boundary_failures: list[str] = []
        boundary_warnings: list[str] = []
        boundary_terms = ("边界", "限制", "停止", "不得", "隐私", "版权", "安全", "boundary", "privacy", "license")
        has_boundary_node = any(node["node_kind"] == "boundary" for node in nodes)
        has_boundary_text = any(any(term in f"{node['title']}\n{node['content']}".lower() for term in boundary_terms) for node in nodes)
        if not nodes:
            boundary_failures.append("SkillPlan 没有节点")
        elif not has_boundary_node and not has_boundary_text:
            boundary_warnings.append("未发现明确的边界/限制/停止条件节点")

        export_failures: list[str] = []
        export_warnings: list[str] = []
        paths = {item.get("path") for item in manifest if isinstance(item, dict)} if isinstance(manifest, list) else set()
        if "SKILL.md" not in paths:
            export_failures.append("file_manifest 缺少 SKILL.md")
        if "references/capabilities.md" not in paths:
            export_failures.append("file_manifest 缺少 references/capabilities.md")
        if not isinstance(manifest, list) or not manifest:
            export_failures.append("file_manifest 为空或格式无效")
        if generated["status"] != "exported":
            export_warnings.append("GeneratedSkill 尚未执行导出，只完成结构预览")

        license_failures: list[str] = []
        license_warnings: list[str] = []
        texts: list[str] = [plan["name"] or "", plan["description"] or ""]
        texts.extend([f"{node['title']}\n{node['content']}" for node in nodes])
        if isinstance(manifest, list):
            for item in manifest:
                if isinstance(item, dict) and isinstance(item.get("content"), str):
                    texts.append(item["content"])
        for content in texts:
            failures, warnings = _scan_license_privacy_text(content)
            license_failures.extend(failures)
            license_warnings.extend(warnings)
        # Keep deterministic and concise.
        license_failures = sorted(set(license_failures))
        license_warnings = sorted(set(license_warnings))

        traceability_result = _result_from_messages(trace_failures, trace_warnings)
        boundary_result = _result_from_messages(boundary_failures, boundary_warnings)
        export_result = _result_from_messages(export_failures, export_warnings)
        license_privacy_result = _result_from_messages(license_failures, license_warnings)
        status = _quality_result_summary([traceability_result, boundary_result, export_result, license_privacy_result])
        summary = {
            "version_fingerprint": version_fingerprint,
            "generated_status": generated["status"],
            "checks": {
                "traceability": {"failures": trace_failures, "warnings": trace_warnings},
                "boundary": {"failures": boundary_failures, "warnings": boundary_warnings},
                "export": {"failures": export_failures, "warnings": export_warnings},
                "license_privacy": {"failures": license_failures, "warnings": license_warnings},
            },
            "feedback_links": {
                "skill_plan_id": generated["skill_plan_id"],
                "generated_skill_id": generated_id,
                "node_ids": [node["id"] for node in nodes],
                "manual_revision_targets": ["Evidence", "Capability", "SkillPlan"],
                "automatic_mutation": False,
            },
        }
        connection.execute(
            """
            INSERT INTO quality_reports (id, generated_skill_id, traceability_result, boundary_result,
                export_result, license_privacy_result, summary_json, status, version_fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (report_id, generated_id, traceability_result, boundary_result, export_result, license_privacy_result, json.dumps(summary, ensure_ascii=False), status, version_fingerprint),
        )
    return get_quality_report(db_path, generated_id)


def get_quality_report(db_path: Path | str, generated_id: str) -> dict[str, Any] | None:
    initialize_database(db_path)
    with closing(connect_database(db_path)) as connection:
        if _generated_row(connection, generated_id) is None:
            raise ProjectNotFound("GeneratedSkill 不存在")
        row = connection.execute("SELECT * FROM quality_reports WHERE generated_skill_id=? ORDER BY created_at DESC, id DESC LIMIT 1", (generated_id,)).fetchone()
        if row is None:
            return None
        item = _row_dict(row)
        item["summary_json"] = _json_loads(item["summary_json"], {})
        return item
