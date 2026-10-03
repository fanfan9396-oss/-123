"""FastAPI application entry point for the S1A/S1B foundation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .db import SCHEMA_VERSION
from .services import (
    DuplicateSource,
    ProjectNotFound,
    ServiceError,
    create_project,
    get_project,
    list_projects,
    import_source,
    create_job,
    get_job,
    list_jobs,
    scan_job,
    parse_job,
    skip_failed_documents,
    list_evidence,
    create_evidence,
    review_evidence,
    evidence_source_map,
    evidence_source_context,
    cluster_capabilities,
    create_capability,
    merge_capabilities,
    review_mechanism,
    get_mechanism,
    list_capabilities,
    update_capability,
    review_capability,
    capability_source_map,
    create_mechanism,
    create_skill_plan,
    get_skill_plan,
    list_skill_plans,
    set_skill_plan_node_evidence,
    review_skill_plan,
    skill_plan_source_map,
    compile_skill_preview,
    export_generated_skill,
    list_generated_skills,
    get_generated_skill,
    get_generated_skill_feedback,
    compare_generated_skills,
    create_scenario,
    list_scenarios,
    create_evaluation,
    list_evaluations,
    run_quality_check,
    get_quality_report,
)

ROOT = Path(__file__).resolve().parents[2]
DIST_DIR = ROOT / "frontend" / "dist"
DEFAULT_DB_PATH = ROOT / "data" / "workbench.sqlite3"


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    goal: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=5000)


class JobCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    goal: str | None = Field(default=None, max_length=2000)
    input_root: str = Field(min_length=1, max_length=4000)


class SkipFailedRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class SelectedFile(BaseModel):
    relative_path: str = Field(min_length=1, max_length=2000)
    filename: str = Field(min_length=1, max_length=500)
    format: str = Field(min_length=1, max_length=8)
    size: int = Field(ge=0, le=5 * 1024 * 1024)
    content: str | None = None
    error: str | None = Field(default=None, max_length=1000)
    original_file_sha256: str | None = Field(default=None, max_length=64)


class ScanJobRequest(BaseModel):
    files: list[SelectedFile] = Field(max_length=500)


class EvidenceExcerptLink(BaseModel):
    excerpt_id: str = Field(min_length=1)
    relation_kind: str = Field(min_length=1)


class EvidenceCreateRequest(BaseModel):
    text: str
    evidence_type: str
    evidence_level: str = "unassessed"
    confidence: float = Field(ge=0, le=1)
    scope: str
    limitations: str
    capability_hint: str | None = None
    excerpt_links: list[EvidenceExcerptLink] = []


class EvidenceReviewRequest(BaseModel):
    action: str
    note: str | None = None


class CapabilityCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    summary: str = ""
    evidence_ids: list[str] = Field(min_length=1)


class CapabilityMergeRequest(BaseModel):
    capability_ids: list[str] = Field(min_length=2)
    name: str = Field(min_length=1, max_length=200)
    summary: str = ""


class CapabilityUpdateRequest(BaseModel):
    name: str | None = None
    summary: str | None = None
    status: str | None = None


class ReviewRequest(BaseModel):
    action: str
    note: str | None = None


class MechanismCreateRequest(BaseModel):
    name: str
    description: str
    scope: str
    limitations: str
    evidence_ids: list[str]


class MechanismReviewRequest(BaseModel):
    action: str
    note: str | None = None


class SkillPlanNodeInput(BaseModel):
    node_kind: str
    title: str
    content: str
    order_index: int | None = None


class SkillPlanCreateRequest(BaseModel):
    name: str
    description: str = ""
    capability_ids: list[str] = []
    mechanism_ids: list[str] = []
    nodes: list[SkillPlanNodeInput] = []


class NodeEvidenceRequest(BaseModel):
    evidence_ids: list[str]


class CompileExportRequest(BaseModel):
    output_path: str = Field(min_length=1, max_length=4000)
    overwrite: bool = False
    confirm: bool = False


class ScenarioCreateRequest(BaseModel):
    generated_skill_id: str | None = None
    title: str = Field(min_length=1, max_length=300)
    input_text: str = Field(min_length=1, max_length=10000)
    boundary_kind: str = Field(min_length=1, max_length=64)
    expected_behavior: str = Field(min_length=1, max_length=5000)
    forbidden_behavior: str = Field(min_length=1, max_length=5000)


class EvaluationCreateRequest(BaseModel):
    observed_behavior: str = Field(min_length=1, max_length=10000)
    verdict: str = Field(min_length=1, max_length=64)
    notes: str = Field(default="", max_length=5000)
    evaluator: str = Field(default="manual", max_length=200)


class SourceImportRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    content: str
    title: str | None = Field(default=None, max_length=500)
    source_type: str = Field(default="other", max_length=64)
    author_or_creator: str | None = Field(default=None, max_length=500)
    published_at: str | None = Field(default=None, max_length=64)
    source_uri: str | None = Field(default=None, max_length=2000)
    original_path: str | None = Field(default=None, max_length=2000)
    original_file_sha256: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=5000)


def create_app(db_path: Path | str | None = None) -> FastAPI:
    app = FastAPI(title="Distillation Workbench", version="0.1.0")
    resolved_db_path = Path(db_path or os.environ.get("DISTILLATION_DB_PATH", DEFAULT_DB_PATH))

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "schema_version": SCHEMA_VERSION}

    @app.post("/api/projects", status_code=201)
    def create_project_endpoint(request: ProjectCreateRequest) -> dict[str, Any]:
        try:
            return create_project(resolved_db_path, request.name, request.goal, request.description)
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/projects")
    def list_projects_endpoint() -> list[dict[str, Any]]:
        return list_projects(resolved_db_path)
    @app.post("/api/projects/{project_id}/jobs", status_code=201)
    def create_job_endpoint(project_id: str, request: JobCreateRequest) -> dict[str, Any]:
        try:
            return create_job(resolved_db_path, project_id, request.name, request.goal, request.input_root)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/jobs")
    def list_jobs_endpoint(project_id: str) -> list[dict[str, Any]]:
        try:
            return list_jobs(resolved_db_path, project_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}")
    def get_job_endpoint(job_id: str) -> dict[str, Any]:
        try:
            return get_job(resolved_db_path, job_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/scan")
    def scan_job_endpoint(job_id: str, request: ScanJobRequest) -> dict[str, Any]:
        try:
            return scan_job(resolved_db_path, job_id, [item.model_dump() for item in request.files])
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/parse")
    def parse_job_endpoint(job_id: str) -> dict[str, Any]:
        try:
            return parse_job(resolved_db_path, job_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/skip-failed")
    def skip_failed_endpoint(job_id: str, request: SkipFailedRequest) -> dict[str, Any]:
        try:
            return skip_failed_documents(resolved_db_path, job_id, request.reason)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}/capabilities")
    def list_capabilities_endpoint(job_id: str) -> list[dict[str, Any]]:
        try:
            return list_capabilities(resolved_db_path, job_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/capabilities/cluster")
    def cluster_capabilities_endpoint(job_id: str) -> dict[str, Any]:
        try:
            return cluster_capabilities(resolved_db_path, job_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/capabilities", status_code=201)
    def create_capability_endpoint(job_id: str, request: CapabilityCreateRequest) -> dict[str, Any]:
        try:
            return create_capability(resolved_db_path, job_id, request.model_dump())
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/capabilities/merge")
    def merge_capabilities_endpoint(job_id: str, request: CapabilityMergeRequest) -> dict[str, Any]:
        try:
            return merge_capabilities(resolved_db_path, job_id, request.capability_ids, request.name, request.summary)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.patch("/api/capabilities/{capability_id}")
    def update_capability_endpoint(capability_id: str, request: CapabilityUpdateRequest) -> dict[str, Any]:
        try:
            return update_capability(resolved_db_path, capability_id, request.model_dump(exclude_unset=True))
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/capabilities/{capability_id}/review")
    def review_capability_endpoint(capability_id: str, request: ReviewRequest) -> dict[str, Any]:
        try:
            return review_capability(resolved_db_path, capability_id, request.action, request.note)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/mechanisms/{mechanism_id}/review")
    def review_mechanism_endpoint(mechanism_id: str, request: MechanismReviewRequest) -> dict[str, Any]:
        try:
            return review_mechanism(resolved_db_path, mechanism_id, request.action, request.note)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/capabilities/{capability_id}/source-map")
    def capability_source_map_endpoint(capability_id: str) -> dict[str, Any]:
        try:
            return capability_source_map(resolved_db_path, capability_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/capabilities/{capability_id}/mechanisms", status_code=201)
    def create_mechanism_endpoint(capability_id: str, request: MechanismCreateRequest) -> dict[str, Any]:
        try:
            return create_mechanism(resolved_db_path, capability_id, request.model_dump())
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}/skill-plans")
    def list_skill_plans_endpoint(job_id: str) -> list[dict[str, Any]]:
        try:
            return list_skill_plans(resolved_db_path, job_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/skill-plans", status_code=201)
    def create_skill_plan_endpoint(job_id: str, request: SkillPlanCreateRequest) -> dict[str, Any]:
        try:
            return create_skill_plan(resolved_db_path, job_id, request.model_dump())
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/skill-plans/{plan_id}")
    def get_skill_plan_endpoint(plan_id: str) -> dict[str, Any]:
        try:
            return get_skill_plan(resolved_db_path, plan_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/skill-plans/{plan_id}/nodes/{node_index}/source-evidence")
    def set_plan_node_evidence_endpoint(plan_id: str, node_index: int, request: NodeEvidenceRequest) -> dict[str, Any]:
        try:
            return set_skill_plan_node_evidence(resolved_db_path, plan_id, node_index, request.evidence_ids)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/skill-plans/{plan_id}/review")
    def review_skill_plan_endpoint(plan_id: str, request: ReviewRequest) -> dict[str, Any]:
        try:
            return review_skill_plan(resolved_db_path, plan_id, request.action, request.note)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/skill-plans/{plan_id}/source-map")
    def skill_plan_source_map_endpoint(plan_id: str) -> dict[str, Any]:
        try:
            return skill_plan_source_map(resolved_db_path, plan_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}/evidence")
    def list_evidence_endpoint(job_id: str) -> list[dict[str, Any]]:
        try:
            return list_evidence(resolved_db_path, job_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/evidence", status_code=201)
    def create_evidence_endpoint(job_id: str, request: EvidenceCreateRequest) -> dict[str, Any]:
        try:
            return create_evidence(resolved_db_path, job_id, request.model_dump())
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/evidence/{evidence_id}/review")
    def review_evidence_endpoint(evidence_id: str, request: EvidenceReviewRequest) -> dict[str, Any]:
        try:
            return review_evidence(resolved_db_path, evidence_id, request.action, request.note)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}/evidence/{evidence_id}/source-context")
    def evidence_source_context_endpoint(job_id: str, evidence_id: str) -> dict[str, Any]:
        try:
            return evidence_source_context(resolved_db_path, job_id, evidence_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/evidence/{evidence_id}/source-map")
    def evidence_source_map_endpoint(evidence_id: str) -> dict[str, Any]:
        try:
            return evidence_source_map(resolved_db_path, evidence_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    @app.post("/api/skill-plans/{plan_id}/compile-preview")
    def compile_preview_endpoint(plan_id: str) -> dict[str, Any]:
        try:
            return compile_skill_preview(resolved_db_path, plan_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/skill-plans/{plan_id}/generated-skills")
    def list_generated_skills_endpoint(plan_id: str) -> list[dict[str, Any]]:
        try:
            return list_generated_skills(resolved_db_path, plan_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/generated-skills/{generated_id}/feedback")
    def generated_skill_feedback_endpoint(generated_id: str) -> dict[str, Any]:
        try:
            return get_generated_skill_feedback(resolved_db_path, generated_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/skill-plans/{plan_id}/generated-skills/compare")
    def compare_generated_skills_endpoint(plan_id: str, from_id: str, to_id: str) -> dict[str, Any]:
        try:
            return compare_generated_skills(resolved_db_path, plan_id, from_id, to_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/generated-skills/{generated_id}")
    def get_generated_skill_endpoint(generated_id: str) -> dict[str, Any]:
        try:
            return get_generated_skill(resolved_db_path, generated_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/generated-skills/{generated_id}/export")
    def export_generated_skill_endpoint(generated_id: str, request: CompileExportRequest) -> dict[str, Any]:
        try:
            return export_generated_skill(resolved_db_path, generated_id, request.output_path, request.overwrite, request.confirm)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            status = 409 if "已存在" in str(exc) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post("/api/skill-plans/{plan_id}/scenarios", status_code=201)
    def create_scenario_endpoint(plan_id: str, request: ScenarioCreateRequest) -> dict[str, Any]:
        try:
            return create_scenario(resolved_db_path, plan_id, request.model_dump())
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/skill-plans/{plan_id}/scenarios")
    def list_scenarios_endpoint(plan_id: str) -> list[dict[str, Any]]:
        try:
            return list_scenarios(resolved_db_path, plan_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/scenarios/{scenario_id}/evaluate", status_code=201)
    def create_evaluation_endpoint(scenario_id: str, request: EvaluationCreateRequest) -> dict[str, Any]:
        try:
            return create_evaluation(resolved_db_path, scenario_id, request.model_dump())
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/skill-plans/{plan_id}/evaluations")
    def list_evaluations_endpoint(plan_id: str) -> list[dict[str, Any]]:
        try:
            return list_evaluations(resolved_db_path, plan_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/generated-skills/{generated_id}/quality-check")
    def quality_check_endpoint(generated_id: str) -> dict[str, Any]:
        try:
            return run_quality_check(resolved_db_path, generated_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/generated-skills/{generated_id}/quality-report")
    def quality_report_endpoint(generated_id: str) -> dict[str, Any] | None:
        try:
            return get_quality_report(resolved_db_path, generated_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}")
    def get_project_endpoint(project_id: str) -> dict[str, Any]:
        try:
            return get_project(resolved_db_path, project_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/sources", status_code=201)
    def import_source_endpoint(project_id: str, request: SourceImportRequest) -> dict[str, Any]:
        try:
            return import_source(
                resolved_db_path,
                project_id,
                filename=request.filename,
                content=request.content,
                title=request.title,
                source_type=request.source_type,
                author_or_creator=request.author_or_creator,
                published_at=request.published_at,
                source_uri=request.source_uri,
                original_path=request.original_path,
                original_file_sha256=request.original_file_sha256,
                notes=request.notes,
            )
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DuplicateSource as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    if DIST_DIR.exists():
        app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

        @app.get("/{path:path}")
        def serve_frontend(path: str) -> FileResponse:
            candidate = DIST_DIR / path
            if path and candidate.is_file() and DIST_DIR in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(DIST_DIR / "index.html")

    return app


app = create_app()
