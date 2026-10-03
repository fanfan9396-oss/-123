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
type QualityReport = { id: string; generated_skill_id: string; traceability_result: string; boundary_result: string; export_result: string; license_privacy_result: string; status: string; version_fingerprint: string; created_at: string; summary_json: { checks?: Record<string,{failures:string[];warnings:string[]}>; feedback_links?: Record<string,unknown> } };
type Project = { id: string; name: string; goal?: string | null; sources: Source[] };
type SelectedFile = { relative_path: string; filename: string; format: string; size: number; content?: string; error?: string; original_file_sha256?: string };

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

  const refreshProjects = async () => {
    const items = await api<Project[]>("/api/projects");
    setProjects(items);
    if (!project && items.length > 0) await openProject(items[0].id);
  };
  const refreshEvidence = async (jobId: string) => { setEvidence(await api<Evidence[]>(`/api/jobs/${jobId}/evidence`)); };
  const refreshS3 = async (jobId: string) => {
    const [caps, plans] = await Promise.all([
      api<Capability[]>(`/api/jobs/${jobId}/capabilities`),
      api<SkillPlan[]>(`/api/jobs/${jobId}/skill-plans`),
    ]);
    setCapabilities(caps); setSkillPlans(plans);
  };
  const refreshJobs = async (projectId: string) => {
    const items = await api<Job[]>(`/api/projects/${projectId}/jobs`);
    setJobs(items);
    if (activeJob) {
      const refreshed = await api<Job>(`/api/jobs/${activeJob.id}`);
      setActiveJob(refreshed);
      await refreshEvidence(refreshed.id);
      if (refreshed.status === "ready_for_evidence") await refreshS3(refreshed.id);
    }
  };
  const openProject = async (projectId: string) => {
    const opened = await api<Project>(`/api/projects/${projectId}`);
    setProject(opened); setActiveJob(null); setEvidence([]); setCapabilities([]); setSkillPlans([]); setS5Scenarios({}); setS5Evaluations({}); setQualityReports({});
    setJobs(await api<Job[]>(`/api/projects/${projectId}/jobs`));
  };
  useEffect(() => { refreshProjects().catch((err: Error) => setError(err.message)); }, []);

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
      setActiveJob(scanned); setJobName(""); setJobGoal(""); setSelectedFiles([]);
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
    try { const generated = await api<GeneratedSkill>(`/api/skill-plans/${plan.id}/compile-preview`, { method: "POST" }); setGeneratedSkills((current) => ({ ...current, [plan.id]: generated })); await refreshS5(plan, generated); setNotice("Skill 编译预览已生成，尚未写入正式目录。"); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  const exportPlan = async (plan: SkillPlan) => {
    const generated = generatedSkills[plan.id]; if (!generated) return;
    const output = window.prompt("输入绝对导出目录："); if (!output?.trim()) return;
    const confirm = window.confirm("确认导出并写入该目录？已有目录默认不会覆盖。"); if (!confirm) return;
    setBusy(true); setError("");
    try { await api(`/api/generated-skills/${generated.id}/export`, { method: "POST", body: JSON.stringify({ output_path: output, overwrite: false, confirm: true }) }); setNotice("Skill 包已导出。"); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
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

  const createScenarioFor = async (plan: SkillPlan) => {
    const generated = generatedSkills[plan.id];
    if (!generated) { setError("请先编译预览，再为该版本创建评测场景。"); return; }
    const title = window.prompt("场景标题：", "正常使用场景")?.trim();
    if (!title) return;
    const boundaryKind = window.prompt("场景类型 normal / ambiguous / failure / safety_boundary：", "normal")?.trim() || "normal";
    const inputText = window.prompt("场景输入：", "用户提交一个需要 Skill 响应的问题")?.trim();
    if (!inputText) return;
    const expected = window.prompt("期望行为：", "说明依据、限制和下一步")?.trim();
    if (!expected) return;
    const forbidden = window.prompt("禁止行为：", "不得编造来源或越过边界")?.trim();
    if (!forbidden) return;
    setBusy(true); setError("");
    try {
      await api<Scenario>(`/api/skill-plans/${plan.id}/scenarios`, { method: "POST", body: JSON.stringify({ generated_skill_id: generated.id, title, input_text: inputText, boundary_kind: boundaryKind, expected_behavior: expected, forbidden_behavior: forbidden }) });
      await refreshS5(plan, generated); setNotice("Scenario 已绑定当前 GeneratedSkill 版本。");
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const evaluateScenario = async (plan: SkillPlan, scenario: Scenario) => {
    const observed = window.prompt("实际观察到的行为：", "")?.trim();
    if (!observed) return;
    const verdict = window.prompt("判定 pass / partial / fail / not_run：", "partial")?.trim() || "not_run";
    const notes = window.prompt("评测备注：", "") || "";
    setBusy(true); setError("");
    try {
      await api<Evaluation>(`/api/scenarios/${scenario.id}/evaluate`, { method: "POST", body: JSON.stringify({ observed_behavior: observed, verdict, notes, evaluator: "local-user" }) });
      await refreshS5(plan); setNotice("Evaluation 已记录；不会自动修改已批准知识。");
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
          <div className="sources-section"><div className="panel-heading"><div><p className="eyebrow">PIPELINE</p><h2>蒸馏任务</h2></div><span className="count">{jobs.length}</span></div>{jobs.length===0?<p className="muted">创建任务后，扫描和解析阶段会显示在这里。</p>:<div className="job-list">{jobs.map(job=><button className={`job-item ${activeJob?.id===job.id?"active":""}`} key={job.id} onClick={()=>api<Job>(`/api/jobs/${job.id}`).then(async (item)=>{setActiveJob(item); await refreshEvidence(item.id); if(item.status === "ready_for_evidence") await refreshS3(item.id);}).catch((err:Error)=>setError(err.message))}><span><strong>{job.name}</strong><small>{job.current_stage} · {job.manifest_count} 个文件</small></span><em>{statusLabel[job.status]||job.status}</em></button>)}</div>}</div>
          {activeJob&&<section className="job-detail"><div className="panel-heading"><div><p className="eyebrow">JOB DETAIL</p><h2>{activeJob.name}</h2><p className="muted">{activeJob.goal||"未填写目标"}</p></div><span className={`job-state ${activeJob.status}`}>{statusLabel[activeJob.status]||activeJob.status}</span></div><div className="pipeline"><span className={activeJob.current_stage==="scan"?"current":"done"}>扫描输入</span><span className={activeJob.current_stage==="parse"?"current":activeJob.status==="ready_for_evidence"?"done":""}>解析文档</span><span className={activeJob.status==="ready_for_evidence"?"done":""}>准备 Evidence</span></div>{activeJob.error_summary&&<div className="alert error">{activeJob.error_summary}</div>}<div className="document-list">{activeJob.documents.map(doc=><article className="document-item" key={doc.id}><div><strong>{doc.filename}</strong><span>{doc.relative_path} · {doc.format.toUpperCase()}{doc.line_count?` · ${doc.line_count} 行`:""}</span>{doc.parse_error&&<small className="parse-error">{doc.parse_error}</small>}</div><em>{statusLabel[doc.status]||doc.status}</em></article>)}</div>{activeJob.status==="review_input"&&activeJob.document_counts.discovered>0&&<button className="primary" disabled={busy} onClick={parseJob}>{busy?"正在解析…":"解析已选文件"}</button>}{activeJob.status==="review_input"&&activeJob.document_counts.failed>0&&<button className="secondary" disabled={busy} onClick={skipFailed}>跳过失败文件…</button>}</section>}
          {activeJob && activeJob.status === "ready_for_evidence" && <section className="evidence-workbench"><div className="panel-heading"><div><p className="eyebrow">EVIDENCE WORKBENCH</p><h2>Evidence 候选与审核</h2><p className="muted">候选必须绑定来源摘录；批准前仍是草稿。</p></div><span className="count">{evidence.length}</span></div><form className="evidence-form" onSubmit={createEvidence}><label>Evidence 文本<textarea value={evidenceText} onChange={e=>setEvidenceText(e.target.value)} rows={3} placeholder="描述一个流程步骤、判断规则或能力线索" required /></label><div className="form-row"><label>类型<select value={evidenceType} onChange={e=>setEvidenceType(e.target.value)}><option value="workflow_step">流程步骤</option><option value="decision_rule">决策规则</option><option value="capability_hint">能力线索</option><option value="terminology">术语</option><option value="dependency">依赖</option><option value="exception">例外</option><option value="quantitative_signal">量化信号</option></select></label><label>证据等级<select value={evidenceLevel} onChange={e=>setEvidenceLevel(e.target.value)}><option value="unassessed">未评估</option><option value="A">A</option><option value="B">B</option><option value="C">C</option><option value="D">D</option></select></label></div><div className="form-row"><label>适用范围<input value={evidenceScope} onChange={e=>setEvidenceScope(e.target.value)} placeholder="适用于什么场景？" /></label><label>限制<input value={evidenceLimitations} onChange={e=>setEvidenceLimitations(e.target.value)} placeholder="不能推断什么？" /></label></div><button className="primary" disabled={busy || !evidenceText.trim()}>{busy ? "保存中…" : "保存 Evidence 草稿"}</button></form><div className="evidence-list">{evidence.map(item=><article className="evidence-item" key={item.id}><div><strong>{item.text}</strong><span>{item.evidence_type} · 等级 {item.evidence_level} · {item.review_status}</span>{item.excerpt_links?.map(link=><small key={`${item.id}-${link.excerpt_id}`}>来源：{link.source_title} · 第 {link.start_line}–{link.end_line} 行</small>)}</div><div className="evidence-actions">{item.review_status !== "approved" && <button className="secondary" disabled={busy} onClick={()=>reviewEvidence(item,"approve")}>批准</button>}{item.review_status !== "rejected" && <button className="secondary" disabled={busy} onClick={()=>reviewEvidence(item,"reject")}>驳回</button>}</div></article>)}</div></section>}
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
