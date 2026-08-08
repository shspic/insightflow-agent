export const REQUIRED_ENGINEERING_ROLES = [
  ["tender_requirement", "招标要求"],
  ["bid_response", "投标响应"],
  ["personnel_equipment_data", "人员设备清单"],
  ["qualification_attachment", "资质附件"],
  ["clarification_document", "项目澄清"],
];

export const OPTIONAL_ENGINEERING_ROLES = [
  ["supplementary_attachment", "补充附件"],
];

export const REVIEW_CHECK_TYPES = [
  ["required_field", "必填字段"],
  ["cross_file_equal", "跨文件一致性"],
  ["numeric_threshold", "数值阈值"],
  ["date_order", "日期顺序"],
  ["document_presence", "材料完整性"],
  ["evidence_required", "证据完整性"],
];

export const REVIEW_OUTPUT_REQUIREMENTS = [
  ["high_risk_requires_evidence", "高风险项必须有证据"],
  ["include_unreviewed_scope", "标明未审查范围"],
  ["group_by_severity", "按风险等级分组"],
];

export const FINDING_STATUS = {
  pending_review: ["待复核", "warning"],
  confirmed: ["已确认", "success"],
  rejected: ["已驳回", "neutral"],
  modified: ["已修改", "info"],
  resolved: ["已解决", "success"],
};

export const FINDING_SEVERITY = {
  high: ["高风险", "danger"],
  medium: ["中风险", "warning"],
  low: ["低风险", "info"],
};

export const REVIEW_RUN_STATUS = {
  draft: ["待开始", "neutral"],
  pending: ["待开始", "neutral"],
  running: ["执行中", "info"],
  completed: ["已完成", "success"],
  failed: ["失败", "danger"],
};

export function splitLines(value = "") {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

export function buildReviewBriefPayload(form) {
  return {
    raw_requirements: form.rawRequirements,
    interpreter_type: "manual",
    interpreted: {
      objectives: splitLines(form.objectives),
      required_check_types: [...form.requiredCheckTypes],
      excluded_check_types: [...form.excludedCheckTypes],
      excluded_scopes: splitLines(form.excludedScopes),
      priority_fields: splitLines(form.priorityFields),
      output_requirements: [...form.outputRequirements],
      clarification_questions: [...(form.clarificationQuestions || [])],
      unsupported_requests: [],
    },
  };
}

export function getMaterialRoleState(profiles = {}) {
  const items = Array.isArray(profiles) ? profiles : Object.values(profiles);
  const readyConfirmed = items.filter((profile) => profile?.status === "ready" && profile.confirmed_role);
  const byRole = new Map(REQUIRED_ENGINEERING_ROLES.map(([role]) => [role, []]));
  readyConfirmed.forEach((profile) => {
    if (byRole.has(profile.confirmed_role)) byRole.get(profile.confirmed_role).push(profile);
  });
  const roles = REQUIRED_ENGINEERING_ROLES.map(([role, label]) => {
    const matches = byRole.get(role);
    return { role, label, count: matches.length, complete: matches.length === 1, fileIds: matches.map((item) => item.file_id) };
  });
  return {
    roles,
    completedCount: roles.filter((item) => item.complete).length,
    missingRoles: roles.filter((item) => item.count === 0),
    duplicatedRoles: roles.filter((item) => item.count > 1),
    complete: roles.every((item) => item.complete),
  };
}

export function filterReviewFindings(findings = [], filters = {}) {
  const query = (filters.query || "").trim().toLocaleLowerCase("zh-CN");
  return findings.filter((finding) => (
    (!filters.severity || filters.severity === "all" || finding.severity === filters.severity)
    && (!filters.status || filters.status === "all" || finding.status === filters.status)
    && (!query || `${finding.issue_code || ""} ${finding.title || ""}`.toLocaleLowerCase("zh-CN").includes(query))
  ));
}

export function selectFindingEvidences(finding, evidences = []) {
  const byId = new Map(evidences.map((evidence) => [Number(evidence.id), evidence]));
  const evidenceIds = finding?.evidence_ids || [];
  return {
    evidences: evidenceIds.map((id) => byId.get(Number(id))).filter(Boolean),
    missingIds: evidenceIds.filter((id) => !byId.has(Number(id))),
  };
}

export function formatEvidenceLocator(evidence, fileName = `文件 #${evidence?.file_id ?? "-"}`) {
  if (!evidence) return fileName;
  if (evidence.locator_type === "pdf_page") return `${fileName} · 第 ${evidence.page_number ?? "-"} 页`;
  if (evidence.locator_type === "spreadsheet_cell") {
    return `${fileName} · ${evidence.sheet_name || "未知工作表"}!${evidence.cell_range || "-"}`;
  }
  if (evidence.locator_type === "text_chunk") return `${fileName} · 文本块 ${evidence.chunk_id ?? "-"}`;
  return `${fileName} · ${evidence.locator_type || "未知定位"}`;
}

export function summarizeFindings(findings = []) {
  const severity = { high: 0, medium: 0, low: 0 };
  const status = { pending_review: 0, confirmed: 0, rejected: 0, modified: 0, resolved: 0 };
  findings.forEach((finding) => {
    if (finding.severity in severity) severity[finding.severity] += 1;
    if (finding.status in status) status[finding.status] += 1;
  });
  return { severity, status };
}

export function getReviewNextStep({ materials, brief, runs = [], findings = [] }) {
  if (!materials?.complete) return { section: "materials", label: "补齐并确认材料角色" };
  if (brief?.status !== "confirmed") return { section: "requirements", label: "填写并确认审查要求" };
  if (!runs.length) return { section: "review", label: "创建审查任务" };
  if (findings.some((finding) => finding.status === "pending_review")) {
    return { section: "findings", label: "复核待确认问题" };
  }
  return { section: "findings", label: "查看审查结果" };
}

export function shortHash(value) {
  return value ? `${value.slice(0, 12)}…` : "—";
}

// ── 审查报告工具函数 ─────────────────────────────────────────────────

export const REPORT_STATUS = {
  ready: ["质量门通过", "success"],
  ready_with_warnings: ["需人工复核", "warning"],
};

export const REPORT_WARNING_CODES = {
  REVIEW_REPORT_PENDING_REVIEW: "报告仍包含待人工复核的问题",
  REVIEW_REPORT_HIGH_RISK_UNREVIEWED: "报告仍包含尚未人工处理的高风险问题",
  REVIEW_REPORT_ACTION_MISSING: "部分问题尚无人工复核动作记录",
  REVIEW_REPORT_OCR_NOT_ENABLED: "报告包含扫描页，当前解析结果明确提示未启用 OCR",
};

export const REPORT_ERROR_SUGGESTIONS = {
  REVIEW_REPORT_RUN_NOT_COMPLETED: "返回执行审查，完成 ReviewRun。",
  REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR: "当前 Run 快照异常，建议创建新的 ReviewRun，不要强行生成。",
  REVIEW_REPORT_EVIDENCE_INTEGRITY_ERROR: "检查 Finding 与 Evidence 定位，必要时重新执行审查。",
  REVIEW_REPORT_GENERATION_ERROR: "资产生成失败，可重试；持续失败时检查服务端日志。",
};

export function sortReviewReports(reports = []) {
  return [...reports].sort((left, right) => Number(right.version || 0) - Number(left.version || 0));
}

export function canGenerateReport(run) {
  if (!run) return false;
  return run.status === "completed" && !run.integrity_error;
}

export function getReportErrorSuggestion(errorCode) {
  return REPORT_ERROR_SUGGESTIONS[errorCode] || "请按错误信息修正后重试。";
}

export function formatFileSize(value) {
  const number = Number(value || 0);
  if (number < 1024) return `${number} B`;
  if (number < 1024 ** 2) return `${(number / 1024).toFixed(1)} KB`;
  if (number < 1024 ** 3) return `${(number / 1024 ** 2).toFixed(1)} MB`;
  return `${(number / 1024 ** 3).toFixed(1)} GB`;
}

export function getReportGenerationState(run) {
  if (!run) return { canGenerate: false, reason: "no_run" };
  if (run.status !== "completed") return { canGenerate: false, reason: "not_completed" };
  if (run.integrity_error) return { canGenerate: false, reason: "integrity_error" };
  return { canGenerate: true, reason: null };
}

export function hasBothReportAssets(assets = []) {
  const types = new Set(assets.map((asset) => asset.asset_type));
  return types.has("markdown") && types.has("pdf");
}

export function missingReportAssets(assets = []) {
  const types = new Set(assets.map((asset) => asset.asset_type));
  const missing = [];
  if (!types.has("markdown")) missing.push("markdown");
  if (!types.has("pdf")) missing.push("pdf");
  return missing;
}

// ── 智能核验（阶段 4C-3）─────────────────────────────────────────────

export const VERIFICATION_RUN_STATUS = {
  planning: ["规划中", "info"],
  running: ["执行中", "info"],
  completed: ["已完成", "success"],
  completed_with_warnings: ["已完成（有警告）", "warning"],
  failed: ["失败", "danger"],
};

// planner 语义：只有 deepseek + fallback_used=false 才算 DeepSeek 规划成功；
// deterministic_fallback 必须如实显示为“模型未通过校验，已使用确定性计划”。
export function describePlanner(run) {
  if (!run) return { label: "—", tone: "neutral" };
  if (run.planner_type === "deepseek" && run.fallback_used === false) {
    return { label: "DeepSeek 规划成功", tone: "success" };
  }
  if (run.planner_type === "deterministic_fallback") {
    return { label: "DeepSeek 输出未通过校验，已使用确定性计划", tone: "warning" };
  }
  return { label: "确定性规划", tone: "neutral" };
}

export const CANDIDATE_DECISION_LABELS = {
  accept: ["已接受为正式证据", "success"],
  reject: ["已拒绝", "neutral"],
};

// 候选决策错误码 → 面向用户的恢复建议（不展示路径、堆栈或敏感字段）
export const CANDIDATE_ERROR_SUGGESTIONS = {
  VERIFICATION_CANDIDATE_NOT_FOUND: "该候选不存在或来源调用失败，请刷新候选列表后重试。",
  VERIFICATION_CANDIDATE_INVALID: "候选未通过服务端一致性校验，已拒绝采纳；可重新运行智能核验生成新候选。",
  VERIFICATION_CANDIDATE_STALE: "材料、角色或索引已变化，该候选已过期；请重新运行智能核验后再决策。",
  VERIFICATION_CANDIDATE_DECISION_CONFLICT: "该候选已有相反的人工决策，决策不可更改。",
  VERIFICATION_RUN_NOT_COMPLETED: "核验尚未完成，等待完成后再进行候选决策。",
};

export function getCandidateErrorSuggestion(errorCode) {
  return CANDIDATE_ERROR_SUGGESTIONS[errorCode] || "请按错误信息修正后重试。";
}

// ToolCall 轨迹按时间顺序（id 升序）；retry 链通过 retry_of_id 可辨认，
// 不合并 prepare / 失败 attempt / 成功 retry 为一条假成功。
export function sortToolCallsByTime(toolCalls = []) {
  return [...toolCalls].sort((a, b) => Number(a.id || 0) - Number(b.id || 0));
}

// 计划展示：retrieve / skip 都保留，skip 也必须可见
export function normalizePlanDecisions(plan) {
  const decisions = Array.isArray(plan?.decisions) ? plan.decisions : [];
  return decisions.map((item) => ({
    findingId: item.finding_id,
    issueCode: item.issue_code,
    decision: item.decision,
    reason: item.reason || "",
    query: item.query || null,
    retrievalMode: item.retrieval_mode || null,
    topK: item.top_k ?? null,
  }));
}

// 候选按 Finding 分组，组内按 (tool_call_id, rank) 稳定排序
export function groupCandidatesByFinding(candidates = []) {
  const groups = new Map();
  candidates.forEach((candidate) => {
    const key = candidate.finding_id ?? "unknown";
    if (!groups.has(key)) {
      groups.set(key, {
        findingId: candidate.finding_id,
        issueCode: candidate.issue_code || `Finding #${candidate.finding_id ?? "-"}`,
        candidates: [],
      });
    }
    groups.get(key).candidates.push(candidate);
  });
  return [...groups.values()].map((group) => ({
    ...group,
    candidates: [...group.candidates].sort(
      (a, b) => (a.tool_call_id - b.tool_call_id) || (a.candidate_rank - b.candidate_rank),
    ),
  }));
}

export function formatCandidateLocator(candidate) {
  if (!candidate) return "—";
  if (candidate.locator_type === "pdf_page") return `第 ${candidate.page_number ?? "-"} 页`;
  if (candidate.locator_type === "spreadsheet_cell") {
    return `${candidate.sheet_name || "未知工作表"}!${candidate.cell_range || "-"}`;
  }
  if (candidate.locator_type === "text_chunk") return "文本块";
  return candidate.locator_type || "未知定位";
}
