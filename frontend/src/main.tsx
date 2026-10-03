import { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Source = { id: string; title: string; format: string; snapshot_sha256: string; excerpt?: { id: string; start_line: number; end_line: number } | null };
type DocumentItem = { id: string; filename: string; relative_path: string; format: string; status: string; line_count?: number | null; parse_error?: string | null; source_id?: string | null };
type Job = { id: string; project_id: string; name: string; goal?: string | null; status: string; current_stage: string; documents: DocumentItem[]; events: Array<{stage:string;status:string;message:string}>; document_counts: Record<string,number>; manifest_count: number; error_summary?: string | null };
type Evidence = { id: string; text: string; evidence_type: string; evidence_level: string; confidence: number; scope: string; limitations: string; review_status: string; review_note?: string | null; excerpt_links?: Array<{ excerpt_id: string; relation_kind: string; source_id: string; source_title: string; start_line: number; end_line: number }> };
type Mechanism = { id: string; capability_id: string; name: string; description: string; scope: string; limitations: string; status: string; evidence_ids: string[] };
type Capability = { id: string; job_id: string; name: string; summary: string; status: string; evidence_ids: string[]; evidence: Evidence[]; mechanisms: Mechanism[] };
type SkillPlan = { id: string; job_id: string; name: string; description: string; status: string; capabilities: Capability[]; mechanisms: Mechanism[]; nodes: Array<{id:string;node_kind:string;title:string;content:string;order_index:number;evidence_ids:string[]}> };
type GeneratedSkill = { id: string; skill_plan_id: string; status: string; files: Array<{path:string;content:string;sha256:string}>; source_map: Record<string, unknown> };
type Scenario = { id: string; skill_plan_id: string; generated_skill_id?: string | null; title: string; input_text: string; boundary_kind: string; expected_behavior: string; forbidden_behavior: string; version_fingerprint: string; created_at: string };
type Evaluation = { id: string; scenario_id: string; skill_plan_id: string; generated_skill_id?: string | null; observed_behavior: string; verdict: string; notes: string; evaluator: string; evaluated_at: string; scenario_title?: string; boundary_kind?: string };
type EvidenceSourceContext = { evidence: { id: string; text: string; review_status: string }; links: Array<{ excerpt_id: string; relation_kind: string; source_id: string; source_title: string; original_path?: string | null; format: string; start_line: number; end_line: number; excerpt_text: string; snapshot_sha256: string }> };
type QualityReport = { id: string; generated_skill_id: string; traceability_result: string; boundary_result: string; export_result: string; license_privacy_result: string; status: string; version_fingerprint: string; created_at: string; summary_json: { checks?: Record<string,{failures:string[];warnings:string[]}>; feedback_links?: Record<string,unknown> } };
type Project = { id: string; name: string; goal?: string | null; sources: Source[] };
type SelectedFile = { relative_path: string; filename: string; format: string; size: number; content?: string; error?: string; original_file_sha256?: string };
type ScenarioFormState = { planId: string; generatedSkillId: string; title: string; inputText: string; boundaryKind: string; expectedBehavior: string; forbiddenBehavior: string };
type EvaluationFormState = { planId: string; scenarioId: string; observedBehavior: string; verdict: string; notes: string; evaluator: string };
type ExportFormState = { planId: string; generatedSkillId: string; outputPath: string; overwrite: boolean; confirm: boolean };

const api = async <T,>(url: string, options?: RequestInit): Promise<T> => {
  const response = await fetch(url, { headers: { "Content-Type": "application/json", ...(options?.headers || {}) }, ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "请求失败");
  return body as T;
};

async function readSelectedFile(file: File): Promise<SelectedFile> {
  const relativePath = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
  const base = { relative_path: relativePath, filename: file.name, format: file.name.split(".").pop()?.toLowerCase() || "", size: file.size };
  try {
    const bytes = await file.arrayBuffer();
    const originalFileSha256 = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))).map((part) => part.toString(16).padStart(2, "0")).join("");
    const content = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    return { ...base, content, original_file_sha256: originalFileSha256 };
  } catch (error) {
    return { ...base, error: error instanceof Error ? `UTF-8 读取失败：${error.message}` : "文件无法按 UTF-8 解码" };
  }
}

const statusLabel: Record<string,string> = { draft: "草稿", scanning: "扫描中", parsing: "解析中", review_input: "待处理", ready_for_evidence: "可进入 Evidence", failed: "失败", cancelled: "已取消", discovered: "待解析", parsed: "已解析", skipped: "已跳过" };

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [skillPlans, setSkillPlans] = useState<SkillPlan[]>([]);
  const [skillPlanName, setSkillPlanName] = useState("");
  const [generatedSkills, setGeneratedSkills] = useState<Record<string, GeneratedSkill>>({});
  const [s5Scenarios, setS5Scenarios] = useState<Record<string, Scenario[]>>({});
  const [s5Evaluations, setS5Evaluations] = useState<Record<string, Evaluation[]>>({});
  const [qualityReports, setQualityReports] = useState<Record<string, QualityReport>>({});
  const [scenarioForm, setScenarioForm] = useState<ScenarioFormState | null>(null);
  const [evaluationForm, setEvaluationForm] = useState<EvaluationFormState | null>(null);
  const [exportForm, setExportForm] = useState<ExportFormState | null>(null);
  const [restoringContext, setRestoringContext] = useState(false);
  const [sourceContext, setSourceContext] = useState<EvidenceSourceContext | null>(null);
  const [evidenceText, setEvidenceText] = useState("");
  const [evidenceType, setEvidenceType] = useState("workflow_step");
  const [evidenceLevel, setEvidenceLevel] = useState("unassessed");
  const [evidenceScope, setEvidenceScope] = useState("");
  const [evidenceLimitations, setEvidenceLimitations] = useState("");
  const [projectName, setProjectName] = useState("");
  const [projectGoal, setProjectGoal] = useState("");
  const [jobName, setJobName] = useState("");
  const [jobGoal, setJobGoal] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const selectedBytes = useMemo(() => selectedFiles.reduce((sum, file) => sum + file.size, 0), [selectedFiles]);

  const contextKey = "distillation-workbench.context.v1";
  const readContext = (): { projectId?: string; jobId?: string; planId?: string; generatedSkillId?: string } => {
    try { return JSON.parse(window.localStorage.getItem(contextKey) || "{}"); } catch { return {}; }
  };
  const patchContext = (patch: Record<string, string | undefined>) => {
    const next = { ...readContext(), ...patch };
    Object.keys(next).forEach((key) => next[key as keyof typeof next] === undefined && delete next[key as keyof typeof next]);
    window.localStorage.setItem(contextKey, JSON.stringify(next));
  };
  const refreshProjects = async () => {
    const items = await api<Project[]>("/api/projects");
    setProjects(items);
    if (!project && items.length > 0) {
      const saved = readContext();
      const target = items.some((item) => item.id === saved.projectId) ? saved.projectId : items[0].id;
      await openProject(target!);
    }
  };
  const refreshEvidence = async (jobId: string) => { setEvidence(await api<Evidence[]>(`/api/jobs/${jobId}/evidence`)); };
  const refreshGenerated = async (plans: SkillPlan[]) => {
    const approved = plans.filter((plan) => plan.status === "approved");
    const entries = await Promise.all(approved.map(async (plan) => [plan.id, await api<GeneratedSkill[]>(`/api/skill-plans/${plan.id}/generated-skills`)] as const));
    const next: Record<string, GeneratedSkill> = {};
    entries.forEach(([planId, skills]) => { if (skills[0]) next[planId] = skills[0]; });
    setGeneratedSkills(next);
    return next;
  };
  const refreshS3 = async (jobId: string) => {
    const [caps, plans] = await Promise.all([
      api<Capability[]>(`/api/jobs/${jobId}/capabilities`),
      api<SkillPlan[]>(`/api/jobs/${jobId}/skill-plans`),
    ]);
    setCapabilities(caps); setSkillPlans(plans); await refreshGenerated(plans); return plans;
  };
  const openJob = async (jobId: string) => {
    const refreshed = await api<Job>(`/api/jobs/${jobId}`);
    setActiveJob(refreshed); patchContext({ jobId: refreshed.id });
    await refreshEvidence(refreshed.id);
    if (refreshed.status === "ready_for_evidence") {
      const plans = await refreshS3(refreshed.id);
      const saved = readContext();
      const plan = plans.find((item) => item.id === saved.planId);
      if (plan) {
        patchContext({ planId: plan.id });
        let generated = generatedSkills[plan.id];
        if (saved.generatedSkillId) {
          try {
            const candidate = await api<GeneratedSkill>(`/api/generated-skills/${saved.generatedSkillId}`);
            if (candidate.skill_plan_id === plan.id) generated = candidate;
          } catch { /* 无效保存上下文会被忽略，页面继续可用。 */ }
        }
        if (generated) {
          setGeneratedSkills((current) => ({ ...current, [plan.id]: generated! }));
          await refreshS5(plan, generated);
        }
      }
    }
  };
  const refreshJobs = async (projectId: string) => {
    const items = await api<Job[]>(`/api/projects/${projectId}/jobs`);
    setJobs(items);
    if (activeJob && items.some((item) => item.id === activeJob.id)) await openJob(activeJob.id);
  };
  const openProject = async (projectId: string) => {
    const opened = await api<Project>(`/api/projects/${projectId}`);
    const projectJobs = await api<Job[]>(`/api/projects/${projectId}/jobs`);
    setProject(opened); setActiveJob(null); setEvidence([]); setCapabilities([]); setSkillPlans([]); setGeneratedSkills({}); setS5Scenarios({}); setS5Evaluations({}); setQualityReports({}); setJobs(projectJobs);
    patchContext({ projectId: opened.id });
    const saved = readContext();
    if (saved.jobId && projectJobs.some((job) => job.id === saved.jobId)) await openJob(saved.jobId);
  };

  useEffect(() => {
    setRestoringContext(true);
    refreshProjects().catch((err: Error) => setError(err.message)).finally(() => setRestoringContext(false));
  }, []);

  const createProject = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const created = await api<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name: projectName, goal: projectGoal || null }) });
      setProjectName(""); setProjectGoal(""); await refreshProjects(); await openProject(created.id);
      setNotice("项目已创建。");
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const createJob = async (event: React.FormEvent) => {
    event.preventDefault(); if (!project) return;
    if (!selectedFiles.length) { setError("请先选择至少一个 Markdown/TXT 文件或目录。"); return; }
    if (selectedFiles.length > 500 || selectedBytes > 25 * 1024 * 1024) { setError("一次最多选择 500 个文件，总大小不超过 25MB。"); return; }
    setBusy(true); setError(""); setNotice("");
    try {
      const created = await api<Job>(`/api/projects/${project.id}/jobs`, { method: "POST", body: JSON.stringify({ name: jobName, goal: jobGoal || null, input_root: "browser-file-picker" }) });
      const files = await Promise.all(selectedFiles.map(readSelectedFile));
      const scanned = await api<Job>(`/api/jobs/${created.id}/scan`, { method: "POST", body: JSON.stringify({ files }) });
      setActiveJob(scanned); patchContext({ projectId: project.id, jobId: scanned.id }); setJobName(""); setJobGoal(""); setSelectedFiles([]);
      const input = document.getElementById("job-files") as HTMLInputElement | null; if (input) input.value = "";
      await refreshJobs(project.id);
      setNotice(`任务已创建，收到 ${scanned.manifest_count} 个支持格式文件。`);
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const parseJob = async () => {
    if (!activeJob) return;
    setBusy(true); setError(""); setNotice("");
    try { const result = await api<Job>(`/api/jobs/${activeJob.id}/parse`, { method: "POST" }); setActiveJob(result); await refreshEvidence(result.id); if(project) { await refreshJobs(project.id); setProject(await api<Project>(`/api/projects/${project.id}`)); } setNotice(result.status === "ready_for_evidence" ? "解析完成，输入已准备好进入 Evidence 阶段。" : "解析结束；请检查失败文件并决定是否跳过。"); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const skipFailed = async () => {
    if (!activeJob) return;
    const reason = window.prompt("请说明跳过失败文件的理由：")?.trim();
    if (!reason) return;
    setBusy(true); setError("");
    try { const result = await api<Job>(`/api/jobs/${activeJob.id}/skip-failed`, { method: "POST", body: JSON.stringify({ reason }) }); setActiveJob(result); await refreshEvidence(result.id); if(project) await refreshJobs(project.id); setNotice("失败文件已按你的理由跳过，任务可以进入 Evidence 阶段。"); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const createEvidence = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!activeJob || !evidenceText.trim()) return;
    const excerptId = activeJob.documents.find((doc) => doc.source_id)?.source_id;
    setBusy(true); setError(""); setNotice("");
    try {
      const detail = await api<Job>(`/api/jobs/${activeJob.id}`);
      const document = detail.documents.find((doc) => doc.source_id);
      if (!document) throw new Error("当前 Job 没有可绑定的来源摘录");
      const projectDetail = project ? await api<Project>(`/api/projects/${project.id}`) : null;
      const source = projectDetail?.sources.find((item) => item.id === document.source_id);
      const linkId = source?.excerpt ? source.excerpt.id : null;
      if (!linkId) throw new Error("当前 Job 没有可绑定的来源摘录");
      await api<Evidence>(`/api/jobs/${activeJob.id}/evidence`, { method: "POST", body: JSON.stringify({ text: evidenceText, evidence_type: evidenceType, evidence_level: evidenceLevel, confidence: 0.5, scope: evidenceScope || "待补充", limitations: evidenceLimitations || "待补充", excerpt_links: [{ excerpt_id: linkId, relation_kind: "direct_support" }] }) });
      await refreshEvidence(activeJob.id); setEvidenceText(""); setEvidenceScope(""); setEvidenceLimitations(""); setNotice("Evidence 草稿已保存，仍需人工审核。");
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  const openEvidenceSourceContext = async (item: Evidence) => {
    if (!activeJob) return;
    setBusy(true); setError("");
    try {
      setSourceContext(await api<EvidenceSourceContext>(`/api/jobs/${activeJob.id}/evidence/${item.id}/source-context`));
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const reviewEvidence = async (item: Evidence, action: string) => {
    setBusy(true); setError("");
    try { await api<Evidence>(`/api/evidence/${item.id}/review`, { method: "POST", body: JSON.stringify({ action, note: action === "approve" ? "已检查来源摘录和限制" : "人工审核驳回" }) }); if(activeJob) { await refreshEvidence(activeJob.id); if(activeJob.status === "ready_for_evidence") await refreshS3(activeJob.id); } setNotice(action === "approve" ? "Evidence 已批准，可作为后续 Capability 输入。" : "Evidence 已驳回。"); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const clusterApprovedEvidence = async () => {
    if (!activeJob) return; setBusy(true); setError(""); setNotice("");
    try { const result = await api<{capabilities:Capability[];created_or_updated:number}>(`/api/jobs/${activeJob.id}/capabilities/cluster`, { method: "POST" }); setCapabilities(result.capabilities); setNotice(`根据已批准 Evidence 整理出 ${result.capabilities.length} 个 Capability 候选。`); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  const reviewCapability = async (item: Capability, action: string) => {
    setBusy(true); setError("");
    try { await api<Capability>(`/api/capabilities/${item.id}/review`, { method: "POST", body: JSON.stringify({ action, note: action === "approve" ? "已检查支撑 Evidence 和边界" : "人工审核驳回" }) }); if(activeJob) await refreshS3(activeJob.id); setNotice(action === "approve" ? "Capability 已批准。" : "Capability 已驳回。"); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  const createMechanismFor = async (item: Capability) => {
    const name = window.prompt("机制名称：", item.name);
    if (!name?.trim()) return;
    setBusy(true); setError("");
    try { await api<Mechanism>(`/api/capabilities/${item.id}/mechanisms`, { method: "POST", body: JSON.stringify({ name, description: item.summary || name, scope: "按关联 Evidence 的适用范围进一步审核", limitations: "需结合每条来源证据限制，不可超出证据外推", evidence_ids: item.evidence_ids }) }); await refreshS3(item.job_id); setNotice("Mechanism 草稿已创建。"); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  const reviewMechanism = async (item: Mechanism, action: string) => {
    setBusy(true); setError("");
    try { await api<Mechanism>(`/api/mechanisms/${item.id}/review`, { method: "POST", body: JSON.stringify({ action, note: action === "approve" ? "已检查 Evidence 支撑和范围限制" : "人工审核驳回" }) }); if(activeJob) await refreshS3(activeJob.id); setNotice(action === "approve" ? "Mechanism 已批准。" : "Mechanism 已驳回。"); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  const createPlanFromApproved = async (event: React.FormEvent) => {
    event.preventDefault(); if (!activeJob) return;
    const approvedCaps = capabilities.filter((cap) => cap.status === "approved");
    if (!approvedCaps.length || !skillPlanName.trim()) { setError("需要至少一个已批准 Capability，并填写 SkillPlan 名称。"); return; }
    setBusy(true); setError("");
    try {
      const mechanisms = approvedCaps.flatMap((cap) => cap.mechanisms.filter((m) => m.status === "approved"));
      const created = await api<SkillPlan>(`/api/jobs/${activeJob.id}/skill-plans`, { method: "POST", body: JSON.stringify({ name: skillPlanName, description: "基于已审核 Capability/Mechanism 生成的编译前计划", capability_ids: approvedCaps.map((cap) => cap.id), mechanism_ids: mechanisms.map((m) => m.id), nodes: approvedCaps.map((cap, index) => ({ node_kind: "workflow_step", title: cap.name, content: cap.summary || cap.name, order_index: index })) }) });
      for (const [index, cap] of approvedCaps.entries()) await api<SkillPlan>(`/api/skill-plans/${created.id}/nodes/${index}/source-evidence`, { method: "PUT", body: JSON.stringify({ evidence_ids: cap.evidence_ids }) });
      setSkillPlanName(""); await refreshS3(activeJob.id); setNotice("SkillPlan 草稿已创建；来源映射完整前不能批准。");
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  const reviewSkillPlan = async (plan: SkillPlan, action: string) => {
    setBusy(true); setError("");
    try { await api<SkillPlan>(`/api/skill-plans/${plan.id}/review`, { method: "POST", body: JSON.stringify({ action, note: action === "approve" ? "已检查 Capability、Mechanism 和全部节点来源映射" : "人工审核驳回" }) }); if(activeJob) await refreshS3(activeJob.id); setNotice(action === "approve" ? "SkillPlan 已批准，可作为 S4 Compiler 输入。" : "SkillPlan 已驳回。"); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const compilePlan = async (plan: SkillPlan) => {
    setBusy(true); setError(""); setNotice("");
    try {
      const generated = await api<GeneratedSkill>(`/api/skill-plans/${plan.id}/compile-preview`, { method: "POST" });
      setGeneratedSkills((current) => ({ ...current, [plan.id]: generated }));
      patchContext({ planId: plan.id, generatedSkillId: generated.id });
      await refreshS5(plan, generated);
      setNotice("Skill 编译预览已生成，尚未写入正式目录。");
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  const exportPlan = (plan: SkillPlan) => {
    const generated = generatedSkills[plan.id]; if (!generated) return;
    setExportForm({ planId: plan.id, generatedSkillId: generated.id, outputPath: "", overwrite: false, confirm: false });
  };
  const submitExportForm = async (event: React.FormEvent) => {
    event.preventDefault(); if (!exportForm) return;
    if (!exportForm.outputPath.trim()) { setError("请输入绝对导出目录。"); return; }
    if (!exportForm.confirm) { setError("请明确确认导出。"); return; }
    setBusy(true); setError("");
    try {
      await api(`/api/generated-skills/${exportForm.generatedSkillId}/export`, { method: "POST", body: JSON.stringify({ output_path: exportForm.outputPath.trim(), overwrite: exportForm.overwrite, confirm: exportForm.confirm }) });
      setExportForm(null); setNotice("Skill 包已导出。");
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };


  const refreshS5 = async (plan: SkillPlan, generated?: GeneratedSkill) => {
    const [scenarios, evaluations] = await Promise.all([
      api<Scenario[]>(`/api/skill-plans/${plan.id}/scenarios`),
      api<Evaluation[]>(`/api/skill-plans/${plan.id}/evaluations`),
    ]);
    setS5Scenarios((current) => ({ ...current, [plan.id]: scenarios }));
    setS5Evaluations((current) => ({ ...current, [plan.id]: evaluations }));
    const currentGenerated = generated || generatedSkills[plan.id];
    if (currentGenerated) {
      try {
        const report = await api<QualityReport | null>(`/api/generated-skills/${currentGenerated.id}/quality-report`);
        if (report) setQualityReports((current) => ({ ...current, [plan.id]: report }));
      } catch {
        // 尚未生成质量报告时保持空态，不自动运行检查。
      }
    }
  };

  const createScenarioFor = (plan: SkillPlan) => {
    const generated = generatedSkills[plan.id];
    if (!generated) { setError("请先编译预览，再为该版本创建评测场景。"); return; }
    setScenarioForm({ planId: plan.id, generatedSkillId: generated.id, title: "", inputText: "", boundaryKind: "normal", expectedBehavior: "", forbiddenBehavior: "" });
  };
  const submitScenarioForm = async (event: React.FormEvent) => {
    event.preventDefault(); if (!scenarioForm) return;
    const plan = skillPlans.find((item) => item.id === scenarioForm.planId);
    if (!plan) { setError("关联 SkillPlan 不存在，请刷新上下文。"); return; }
    setBusy(true); setError("");
    try {
      const created = await api<Scenario>(`/api/skill-plans/${plan.id}/scenarios`, { method: "POST", body: JSON.stringify({ generated_skill_id: scenarioForm.generatedSkillId, title: scenarioForm.title.trim(), input_text: scenarioForm.inputText.trim(), boundary_kind: scenarioForm.boundaryKind, expected_behavior: scenarioForm.expectedBehavior.trim(), forbidden_behavior: scenarioForm.forbiddenBehavior.trim() }) });
      setScenarioForm(null); await refreshS5(plan, generatedSkills[plan.id]); setNotice(`Scenario「${created.title}」已绑定当前 GeneratedSkill 版本。`);
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const evaluateScenario = (plan: SkillPlan, scenario: Scenario) => {
    setEvaluationForm({ planId: plan.id, scenarioId: scenario.id, observedBehavior: "", verdict: "partial", notes: "", evaluator: "local-user" });
  };
  const submitEvaluationForm = async (event: React.FormEvent) => {
    event.preventDefault(); if (!evaluationForm) return;
    const plan = skillPlans.find((item) => item.id === evaluationForm.planId);
    if (!plan) { setError("关联 SkillPlan 不存在，请刷新上下文。"); return; }
    setBusy(true); setError("");
    try {
      await api<Evaluation>(`/api/scenarios/${evaluationForm.scenarioId}/evaluate`, { method: "POST", body: JSON.stringify({ observed_behavior: evaluationForm.observedBehavior.trim(), verdict: evaluationForm.verdict, notes: evaluationForm.notes.trim(), evaluator: evaluationForm.evaluator.trim() || "manual" }) });
      setEvaluationForm(null); await refreshS5(plan); setNotice("Evaluation 已记录；不会自动修改已批准知识。");
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const runQualityCheckFor = async (plan: SkillPlan) => {
    const generated = generatedSkills[plan.id];
    if (!generated) { setError("请先编译预览，再执行质量检查。"); return; }
    setBusy(true); setError("");
    try {
      const report = await api<QualityReport>(`/api/generated-skills/${generated.id}/quality-check`, { method: "POST" });
      setQualityReports((current) => ({ ...current, [plan.id]: report }));
      await refreshS5(plan, generated); setNotice(`质量检查完成：${report.status}。失败只进入反馈，不会自动改写知识。`);
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  return <main className="shell">
    <section className="hero"><p className="eyebrow">DISTILLATION WORKBENCH · S2A</p><h1>知识蒸馏工作台</h1><p className="lede">从本地资料出发，把证据整理成可审核、可复用的 Skill。</p></section>
    {error && <div className="alert error" role="alert">{error}</div>}{notice && <div className="alert success" role="status">{notice}</div>}
    {restoringContext && <div className="alert info" role="status">正在恢复最近工作上下文…</div>}
    {scenarioForm && <section className="modal-card" aria-labelledby="scenario-form-title"><div className="panel-heading"><div><p className="eyebrow">SCENARIO FORM</p><h2 id="scenario-form-title">新增评测场景</h2><p className="muted">场景将绑定当前 GeneratedSkill 版本；取消不会写入数据。</p></div><button type="button" className="secondary" onClick={() => setScenarioForm(null)}>取消</button></div><form className="modal-form" onSubmit={submitScenarioForm}><div className="form-row"><label>场景标题<input required maxLength={300} value={scenarioForm.title} onChange={(event) => setScenarioForm({ ...scenarioForm, title: event.target.value })} /></label><label>场景类型<select value={scenarioForm.boundaryKind} onChange={(event) => setScenarioForm({ ...scenarioForm, boundaryKind: event.target.value })}><option value="normal">normal · 正常</option><option value="ambiguous">ambiguous · 含糊</option><option value="failure">failure · 失败</option><option value="safety_boundary">safety_boundary · 安全边界</option></select></label></div><label>场景输入<textarea required maxLength={10000} value={scenarioForm.inputText} onChange={(event) => setScenarioForm({ ...scenarioForm, inputText: event.target.value })} /></label><div className="form-row"><label>期望行为<textarea required maxLength={5000} value={scenarioForm.expectedBehavior} onChange={(event) => setScenarioForm({ ...scenarioForm, expectedBehavior: event.target.value })} /></label><label>禁止行为<textarea required maxLength={5000} value={scenarioForm.forbiddenBehavior} onChange={(event) => setScenarioForm({ ...scenarioForm, forbiddenBehavior: event.target.value })} /></label></div><button className="primary" disabled={busy}>保存 Scenario</button></form></section>}
    {evaluationForm && <section className="modal-card" aria-labelledby="evaluation-form-title"><div className="panel-heading"><div><p className="eyebrow">EVALUATION FORM</p><h2 id="evaluation-form-title">记录场景评测</h2><p className="muted">评测只记录当前版本结果，不会自动修改 approved 知识。</p></div><button type="button" className="secondary" onClick={() => setEvaluationForm(null)}>取消</button></div><form className="modal-form" onSubmit={submitEvaluationForm}><label>实际观察到的行为<textarea required maxLength={10000} value={evaluationForm.observedBehavior} onChange={(event) => setEvaluationForm({ ...evaluationForm, observedBehavior: event.target.value })} /></label><div className="form-row"><label>判定<select value={evaluationForm.verdict} onChange={(event) => setEvaluationForm({ ...evaluationForm, verdict: event.target.value })}><option value="pass">pass · 通过</option><option value="partial">partial · 部分通过</option><option value="fail">fail · 失败</option><option value="not_run">not_run · 未运行</option></select></label><label>评测者<input required maxLength={200} value={evaluationForm.evaluator} onChange={(event) => setEvaluationForm({ ...evaluationForm, evaluator: event.target.value })} /></label></div><label>评测备注<textarea maxLength={5000} value={evaluationForm.notes} onChange={(event) => setEvaluationForm({ ...evaluationForm, notes: event.target.value })} /></label><button className="primary" disabled={busy}>保存 Evaluation</button></form></section>}
    {exportForm && <section className="modal-card" aria-labelledby="export-form-title"><div className="panel-heading"><div><p className="eyebrow">EXPORT FORM</p><h2 id="export-form-title">导出 Skill 包</h2><p className="muted">必须使用绝对路径；默认不覆盖已有目录。</p></div><button type="button" className="secondary" onClick={() => setExportForm(null)}>取消</button></div><form className="modal-form" onSubmit={submitExportForm}><label>绝对导出目录<input required placeholder="例如：C:\Users\Administrator\Desktop\output\my-skill" value={exportForm.outputPath} onChange={(event) => setExportForm({ ...exportForm, outputPath: event.target.value })} /></label><label className="checkbox-label"><input type="checkbox" checked={exportForm.overwrite} onChange={(event) => setExportForm({ ...exportForm, overwrite: event.target.checked })} />明确允许覆盖已存在目录</label><label className="checkbox-label"><input type="checkbox" checked={exportForm.confirm} onChange={(event) => setExportForm({ ...exportForm, confirm: event.target.checked })} />我确认导出并写入本地目录</label><button className="primary" disabled={busy || !exportForm.confirm}>确认导出</button></form></section>}
    {sourceContext && <section className="modal-card source-context-card" aria-labelledby="source-context-title"><div className="panel-heading"><div><p className="eyebrow">SOURCE CONTEXT</p><h2 id="source-context-title">Evidence 原文定位</h2><p className="muted">只读显示 Evidence 已绑定的 Excerpt 和 Source，不修改来源快照。</p></div><button type="button" className="secondary" onClick={() => setSourceContext(null)}>关闭</button></div><div className="source-context-evidence"><strong>{sourceContext.evidence.text}</strong><span>审核状态：{sourceContext.evidence.review_status}</span></div><div className="source-context-links">{sourceContext.links.map((link) => <article className="source-context-link" key={`${link.excerpt_id}-${link.relation_kind}`}><div className="capability-header"><strong>{link.source_title}</strong><span>{link.relation_kind}</span></div><small>{link.original_path || "未记录原路径"} · {link.format.toUpperCase()} · 第 {link.start_line}–{link.end_line} 行</small><pre>{link.excerpt_text}</pre><code>snapshot: {link.snapshot_sha256}</code></article>)}</div></section>}
    <div className="workspace-grid">
      <aside className="panel project-panel">
        <div className="panel-heading"><div><p className="eyebrow">PROJECTS</p><h2>蒸馏项目</h2></div><span className="count">{projects.length}</span></div>
        <div className="project-list">{projects.map(item => <button className={`project-item ${project?.id===item.id?"active":""}`} key={item.id} onClick={()=>openProject(item.id).catch((err:Error)=>setError(err.message))}><strong>{item.name}</strong><span>{item.goal || "尚未填写目标"}</span></button>)}{projects.length===0&&<p className="muted">还没有项目。</p>}</div>
        <form className="stack-form" onSubmit={createProject}><label>新项目名称<input value={projectName} onChange={e=>setProjectName(e.target.value)} placeholder="例如：亲密关系蒸馏" required /></label><label>项目目标<textarea value={projectGoal} onChange={e=>setProjectGoal(e.target.value)} placeholder="希望从资料中沉淀出什么？" rows={3}/></label><button className="primary" disabled={busy||!projectName.trim()}>{busy?"处理中…":"创建项目"}</button></form>
      </aside>
      <section className="panel main-panel">
        {!project?<div className="empty-state embedded"><div className="icon">✦</div><h2>先创建一个蒸馏项目</h2><p>项目和来源快照保存在本机。</p></div>:<>
          <div className="panel-heading"><div><p className="eyebrow">CURRENT PROJECT</p><h2>{project.name}</h2><p className="muted">{project.goal||"本地知识蒸馏项目"}</p></div><span className="status-pill">本地离线</span></div>
          <form className="import-card" onSubmit={createJob}><div><p className="eyebrow">DISTILLATION JOB</p><h2>创建蒸馏任务</h2><p className="muted">选择文件或目录。只会读取你明确选择的 Markdown/TXT 文件，不扫描其他路径，也不会上传到外部。</p></div><div className="form-row"><label>任务名称<input value={jobName} onChange={e=>setJobName(e.target.value)} placeholder="例如：整理亲密关系沟通方法" required /></label><label>蒸馏目标<input value={jobGoal} onChange={e=>setJobGoal(e.target.value)} placeholder="希望提取什么能力？" /></label></div><div className="file-picker-row"><label className="file-picker" htmlFor="job-files"><span>选择多个 Markdown/TXT 文件</span><input id="job-files" type="file" multiple accept=".md,.txt,text/markdown,text/plain" onChange={e=>setSelectedFiles(Array.from(e.target.files||[]))}/></label><label className="file-picker" htmlFor="job-directory"><span>选择资料目录</span><input id="job-directory" type="file" multiple accept=".md,.txt,text/markdown,text/plain" {...({webkitdirectory:""} as Record<string,string>)} onChange={e=>setSelectedFiles(Array.from(e.target.files||[]))}/></label></div><p className="selection-summary">{selectedFiles.length?`已选择 ${selectedFiles.length} 个文件（${(selectedBytes/1024).toFixed(1)} KB）`:"尚未选择输入文件"}</p><button className="primary" disabled={busy||!jobName.trim()||!selectedFiles.length}>{busy?"正在扫描并保存…":"创建任务并扫描"}</button></form>
          <div className="sources-section"><div className="panel-heading"><div><p className="eyebrow">PIPELINE</p><h2>蒸馏任务</h2></div><span className="count">{jobs.length}</span></div>{jobs.length===0?<p className="muted">创建任务后，扫描和解析阶段会显示在这里。</p>:<div className="job-list">{jobs.map(job=><button className={`job-item ${activeJob?.id===job.id?"active":""}`} key={job.id} onClick={()=>openJob(job.id).catch((err:Error)=>setError(err.message))}><span><strong>{job.name}</strong><small>{job.current_stage} · {job.manifest_count} 个文件</small></span><em>{statusLabel[job.status]||job.status}</em></button>)}</div>}</div>
          {activeJob&&<section className="job-detail"><div className="panel-heading"><div><p className="eyebrow">JOB DETAIL</p><h2>{activeJob.name}</h2><p className="muted">{activeJob.goal||"未填写目标"}</p></div><span className={`job-state ${activeJob.status}`}>{statusLabel[activeJob.status]||activeJob.status}</span></div><div className="pipeline"><span className={activeJob.current_stage==="scan"?"current":"done"}>扫描输入</span><span className={activeJob.current_stage==="parse"?"current":activeJob.status==="ready_for_evidence"?"done":""}>解析文档</span><span className={activeJob.status==="ready_for_evidence"?"done":""}>准备 Evidence</span></div>{activeJob.error_summary&&<div className="alert error">{activeJob.error_summary}</div>}<div className="document-list">{activeJob.documents.map(doc=><article className="document-item" key={doc.id}><div><strong>{doc.filename}</strong><span>{doc.relative_path} · {doc.format.toUpperCase()}{doc.line_count?` · ${doc.line_count} 行`:""}</span>{doc.parse_error&&<small className="parse-error">{doc.parse_error}</small>}</div><em>{statusLabel[doc.status]||doc.status}</em></article>)}</div>{activeJob.status==="review_input"&&activeJob.document_counts.discovered>0&&<button className="primary" disabled={busy} onClick={parseJob}>{busy?"正在解析…":"解析已选文件"}</button>}{activeJob.status==="review_input"&&activeJob.document_counts.failed>0&&<button className="secondary" disabled={busy} onClick={skipFailed}>跳过失败文件…</button>}</section>}
          {activeJob && activeJob.status === "ready_for_evidence" && <section className="evidence-workbench"><div className="panel-heading"><div><p className="eyebrow">EVIDENCE WORKBENCH</p><h2>Evidence 候选与审核</h2><p className="muted">候选必须绑定来源摘录；批准前仍是草稿。</p></div><span className="count">{evidence.length}</span></div><form className="evidence-form" onSubmit={createEvidence}><label>Evidence 文本<textarea value={evidenceText} onChange={e=>setEvidenceText(e.target.value)} rows={3} placeholder="描述一个流程步骤、判断规则或能力线索" required /></label><div className="form-row"><label>类型<select value={evidenceType} onChange={e=>setEvidenceType(e.target.value)}><option value="workflow_step">流程步骤</option><option value="decision_rule">决策规则</option><option value="capability_hint">能力线索</option><option value="terminology">术语</option><option value="dependency">依赖</option><option value="exception">例外</option><option value="quantitative_signal">量化信号</option></select></label><label>证据等级<select value={evidenceLevel} onChange={e=>setEvidenceLevel(e.target.value)}><option value="unassessed">未评估</option><option value="A">A</option><option value="B">B</option><option value="C">C</option><option value="D">D</option></select></label></div><div className="form-row"><label>适用范围<input value={evidenceScope} onChange={e=>setEvidenceScope(e.target.value)} placeholder="适用于什么场景？" /></label><label>限制<input value={evidenceLimitations} onChange={e=>setEvidenceLimitations(e.target.value)} placeholder="不能推断什么？" /></label></div><button className="primary" disabled={busy || !evidenceText.trim()}>{busy ? "保存中…" : "保存 Evidence 草稿"}</button></form><div className="evidence-list">{evidence.map(item=><article className="evidence-item" key={item.id}><div><strong>{item.text}</strong><span>{item.evidence_type} · 等级 {item.evidence_level} · {item.review_status}</span>{item.excerpt_links?.map(link=><small key={`${item.id}-${link.excerpt_id}`}>来源：{link.source_title} · 第 {link.start_line}–{link.end_line} 行</small>)}</div><div className="evidence-actions"><button type="button" className="secondary" disabled={busy} onClick={()=>openEvidenceSourceContext(item)}>查看原文定位</button>{item.review_status !== "approved" && <button className="secondary" disabled={busy} onClick={()=>reviewEvidence(item,"approve")}>批准</button>}{item.review_status !== "rejected" && <button className="secondary" disabled={busy} onClick={()=>reviewEvidence(item,"reject")}>驳回</button>}</div></article>)}</div></section>}
        {activeJob && activeJob.status === "ready_for_evidence" && <section className="s3-workbench"><div className="panel-heading"><div><p className="eyebrow">CAPABILITY & SKILL PLAN</p><h2>能力聚类与 Skill Plan</h2><p className="muted">只使用已批准 Evidence；不在此阶段生成或导出最终 Skill 文件。</p></div><button className="secondary" disabled={busy || !evidence.some(e => e.review_status === "approved")} onClick={clusterApprovedEvidence}>根据已批准 Evidence 生成候选</button></div>
          <div className="capability-list">{capabilities.map(cap=><article className="capability-card" key={cap.id}><div className="capability-header"><div><strong>{cap.name}</strong><p>{cap.summary}</p></div><span className={`job-state ${cap.status}`}>{cap.status}</span></div><div className="evidence-chip-list">{cap.evidence.map(ev=><span className="evidence-chip" key={ev.id}>{ev.text} · {ev.evidence_level}</span>)}</div><div className="capability-actions">{cap.status !== "approved" && <button className="secondary" disabled={busy} onClick={()=>reviewCapability(cap,"approve")}>批准 Capability</button>}{cap.status !== "rejected" && <button className="secondary" disabled={busy} onClick={()=>reviewCapability(cap,"reject")}>驳回</button>}{cap.status === "approved" && <button className="secondary" disabled={busy || !cap.evidence_ids.length} onClick={()=>createMechanismFor(cap)}>创建 Mechanism 草稿</button>}</div>{cap.mechanisms.map(mech=><div className="mechanism-row" key={mech.id}><span><strong>{mech.name}</strong> · {mech.status}</span>{mech.status !== "approved" && <button className="secondary" disabled={busy} onClick={()=>reviewMechanism(mech,"approve")}>批准 Mechanism</button>}</div>)}</article>)}</div>
          <form className="plan-create" onSubmit={createPlanFromApproved}><label>SkillPlan 名称<input value={skillPlanName} onChange={e=>setSkillPlanName(e.target.value)} placeholder="例如：本地资料 Evidence 提取 Skill" /></label><button className="primary" disabled={busy || !capabilities.some(c=>c.status === "approved")}>从已批准 Capability 创建 SkillPlan 草稿</button></form>
          <div className="plan-list">{skillPlans.map(plan=><article className="plan-card" key={plan.id}><div className="capability-header"><div><strong>{plan.name}</strong><p>{plan.capabilities.length} 个 Capability · {plan.mechanisms.length} 个 Mechanism · {plan.nodes.length} 个节点</p></div><span className={`job-state ${plan.status}`}>{plan.status}</span></div><div className="evidence-chip-list">{plan.nodes.map(node=><span className="evidence-chip" key={node.id}>{node.title} · {node.evidence_ids.length} 条来源</span>)}</div><div className="capability-actions">{plan.status !== "approved" && <button className="secondary" disabled={busy} onClick={()=>reviewSkillPlan(plan,"approve")}>审核并批准 Plan</button>}{plan.status !== "rejected" && <button className="secondary" disabled={busy} onClick={()=>reviewSkillPlan(plan,"reject")}>驳回 Plan</button>}{plan.status === "approved" && <button className="secondary" disabled={busy} onClick={()=>compilePlan(plan)}>编译预览</button>}{plan.status === "approved" && generatedSkills[plan.id] && <button className="primary" disabled={busy} onClick={()=>exportPlan(plan)}>导出 Skill 包</button>}{plan.status === "approved" && generatedSkills[plan.id] && <button className="secondary" disabled={busy} onClick={()=>createScenarioFor(plan)}>新增评测场景</button>}{plan.status === "approved" && generatedSkills[plan.id] && <button className="secondary" disabled={busy} onClick={()=>runQualityCheckFor(plan)}>质量检查</button>}</div>{generatedSkills[plan.id] && <div className="compiler-preview"><strong>编译预览：{generatedSkills[plan.id].files.length} 个文件</strong>{generatedSkills[plan.id].files.map(file=><div className="preview-file" key={file.path}><code>{file.path}</code><span>{file.content.slice(0, 160)}{file.content.length > 160 ? "…" : ""}</span></div>)}</div>}{generatedSkills[plan.id] && <div className="s5-panel"><strong>S5 场景评测与质量闭环</strong><p className="muted">场景和评测绑定当前 GeneratedSkill 版本；质量失败只给出反馈入口，不自动修改已批准知识。</p><div className="evidence-chip-list">{(s5Scenarios[plan.id]||[]).map(s=><span className="evidence-chip" key={s.id}>{s.boundary_kind} · {s.title}<button className="inline-action" disabled={busy} onClick={()=>evaluateScenario(plan,s)}>记录评测</button></span>)}</div>{(s5Evaluations[plan.id]||[]).length>0 && <div className="evaluation-list">{(s5Evaluations[plan.id]||[]).map(ev=><small key={ev.id}>{ev.scenario_title||ev.scenario_id} · {ev.verdict} · {ev.evaluator}</small>)}</div>}{qualityReports[plan.id] && <div className={`quality-report ${qualityReports[plan.id].status}`}><strong>质量报告：{qualityReports[plan.id].status}</strong><span>Trace {qualityReports[plan.id].traceability_result} · Boundary {qualityReports[plan.id].boundary_result} · Export {qualityReports[plan.id].export_result} · License/Privacy {qualityReports[plan.id].license_privacy_result}</span></div>}</div>}</article>)}</div>
        </section>}
        <div className="sources-section"><div className="panel-heading"><div><p className="eyebrow">SOURCES</p><h2>项目来源快照</h2></div><span className="count">{project.sources.length}</span></div>{project.sources.length===0?<p className="muted">完成任务解析后，来源快照会显示在这里。</p>:<div className="source-list">{project.sources.map(source=><article className="source-item" key={source.id}><div><strong>{source.title}</strong><span>{source.format.toUpperCase()} · {source.excerpt?.start_line}–{source.excerpt?.end_line} 行</span></div><code>{source.snapshot_sha256.slice(0,12)}…</code></article>)}</div>}</div>
        </>}
      </section>
    </div>
  </main>;
}

createRoot(document.getElementById("root")!).render(<App />);
