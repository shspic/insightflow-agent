import assert from "node:assert/strict";
import test from "node:test";

import {
  buildReviewBriefPayload,
  canGenerateReport,
  describePlanner,
  filterReviewFindings,
  formatCandidateLocator,
  formatEvidenceLocator,
  formatFileSize,
  getCandidateErrorSuggestion,
  getMaterialRoleState,
  getReportErrorSuggestion,
  getReportGenerationState,
  getReviewNextStep,
  groupCandidatesByFinding,
  hasBothReportAssets,
  missingReportAssets,
  normalizePlanDecisions,
  sortToolCallsByTime,
  selectFindingEvidences,
  REPORT_STATUS,
  REPORT_WARNING_CODES,
  shortHash,
  sortReviewReports,
} from "./engineeringReview.js";

test("五种工程角色仅在已就绪且人工确认后计入完成度，并识别重复角色", () => {
  const state = getMaterialRoleState([
    { file_id: 1, status: "ready", confirmed_role: "tender_requirement" },
    { file_id: 2, status: "ready", confirmed_role: "bid_response" },
    { file_id: 3, status: "ready", confirmed_role: "bid_response" },
    { file_id: 4, status: "ready", suggested_role: "personnel_equipment_data", confirmed_role: null },
    { file_id: 5, status: "failed", confirmed_role: "qualification_attachment" },
    { file_id: 6, status: "ready", confirmed_role: "clarification_document" },
    { file_id: 7, status: "ready", confirmed_role: "supplementary_attachment" },
  ]);

  assert.equal(state.completedCount, 2);
  assert.deepEqual(state.duplicatedRoles.map((item) => item.role), ["bid_response"]);
  assert.deepEqual(state.missingRoles.map((item) => item.role), [
    "personnel_equipment_data",
    "qualification_attachment",
  ]);
  assert.equal(state.complete, false);
});

test("Finding 可按风险、状态以及 issue_code 或标题组合筛选", () => {
  const findings = [
    { issue_code: "SYN-EQ-001", title: "项目名称不一致", severity: "high", status: "pending_review" },
    { issue_code: "SYN-NUM-001", title: "人员数量不足", severity: "medium", status: "confirmed" },
  ];
  assert.deepEqual(filterReviewFindings(findings, { severity: "high", status: "all", query: "项目" }), [findings[0]]);
  assert.deepEqual(filterReviewFindings(findings, { severity: "all", status: "confirmed", query: "syn-num" }), [findings[1]]);
});

test("Evidence locator 按 PDF、Excel 和文本块格式化", () => {
  assert.equal(formatEvidenceLocator({ locator_type: "pdf_page", page_number: 1 }, "投标响应.pdf"), "投标响应.pdf · 第 1 页");
  assert.equal(formatEvidenceLocator({ locator_type: "spreadsheet_cell", sheet_name: "人员清单", cell_range: "B3" }, "人员设备清单.xlsx"), "人员设备清单.xlsx · 人员清单!B3");
  assert.equal(formatEvidenceLocator({ locator_type: "text_chunk", chunk_id: 1 }, "项目澄清.md"), "项目澄清.md · 文本块 1");
});

test("Finding 只关联 evidence_ids 指定的 Evidence，并报告缺失 ID", () => {
  const selected = selectFindingEvidences(
    { evidence_ids: [2, 9] },
    [{ id: 1, quote: "不应出现" }, { id: 2, quote: "应出现" }],
  );
  assert.deepEqual(selected.evidences.map((item) => item.id), [2]);
  assert.deepEqual(selected.missingIds, [9]);
});

test("ReviewRun 下一步建议按材料、Brief、Run 和待复核问题推进", () => {
  assert.equal(getReviewNextStep({ materials: { complete: false } }).section, "materials");
  assert.equal(getReviewNextStep({ materials: { complete: true }, brief: null }).section, "requirements");
  assert.equal(getReviewNextStep({ materials: { complete: true }, brief: { status: "confirmed" }, runs: [] }).section, "review");
  assert.equal(getReviewNextStep({
    materials: { complete: true }, brief: { status: "confirmed" }, runs: [{ id: 1 }],
    findings: [{ status: "pending_review" }],
  }).section, "findings");
});

test("ReviewBrief 表单转换为 manual 白名单 API payload", () => {
  const payload = buildReviewBriefPayload({
    rawRequirements: "重点检查日期与证据。",
    objectives: "核对关键字段\n定位高风险证据",
    requiredCheckTypes: ["required_field", "date_order"],
    excludedCheckTypes: ["numeric_threshold"],
    excludedScopes: "价格评分\n历史报告",
    priorityFields: "bid_response.project_name",
    outputRequirements: ["group_by_severity"],
  });
  assert.deepEqual(payload, {
    raw_requirements: "重点检查日期与证据。",
    interpreter_type: "manual",
    interpreted: {
      objectives: ["核对关键字段", "定位高风险证据"],
      required_check_types: ["required_field", "date_order"],
      excluded_check_types: ["numeric_threshold"],
      excluded_scopes: ["价格评分", "历史报告"],
      priority_fields: ["bid_response.project_name"],
      output_requirements: ["group_by_severity"],
      clarification_questions: [],
      unsupported_requests: [],
    },
  });
});

// ── 审查报告工具函数测试 ───────────────────────────────────────────

test("sortReviewReports 按版本从高到低排序", () => {
  const sorted = sortReviewReports([
    { id: 3, version: 1 },
    { id: 1, version: 3 },
    { id: 2, version: 2 },
  ]);
  assert.deepEqual(sorted.map((r) => r.version), [3, 2, 1]);
});

test("canGenerateReport 只允许 completed 且无 integrity_error 的 Run", () => {
  assert.equal(canGenerateReport({ status: "completed", integrity_error: null }), true);
  assert.equal(canGenerateReport({ status: "completed" }), true);
  assert.equal(canGenerateReport({ status: "failed", integrity_error: null }), false);
  assert.equal(canGenerateReport({ status: "pending", integrity_error: null }), false);
  assert.equal(canGenerateReport({ status: "completed", integrity_error: { error_code: "ERR" } }), false);
  assert.equal(canGenerateReport(null), false);
});

test("getReportGenerationState 返回清晰的前置条件", () => {
  assert.deepEqual(getReportGenerationState(null), { canGenerate: false, reason: "no_run" });
  assert.deepEqual(getReportGenerationState({ status: "running" }), { canGenerate: false, reason: "not_completed" });
  assert.deepEqual(getReportGenerationState({ status: "completed", integrity_error: {} }), { canGenerate: false, reason: "integrity_error" });
  assert.deepEqual(getReportGenerationState({ status: "completed" }), { canGenerate: true, reason: null });
});

test("getReportErrorSuggestion 返回已知错误码的恢复建议", () => {
  assert.ok(getReportErrorSuggestion("REVIEW_REPORT_RUN_NOT_COMPLETED").includes("ReviewRun"));
  assert.ok(getReportErrorSuggestion("REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR").includes("快照异常"));
  assert.ok(getReportErrorSuggestion("REVIEW_REPORT_EVIDENCE_INTEGRITY_ERROR").includes("Evidence"));
  assert.ok(getReportErrorSuggestion("REVIEW_REPORT_GENERATION_ERROR").includes("资产生成失败"));
  // 未知错误码回退
  assert.ok(getReportErrorSuggestion("UNKNOWN_CODE").includes("重试"));
});

test("formatFileSize 格式化字节为可读单位", () => {
  assert.equal(formatFileSize(0), "0 B");
  assert.equal(formatFileSize(500), "500 B");
  assert.equal(formatFileSize(2048), "2.0 KB");
  assert.equal(formatFileSize(1048576), "1.0 MB");
  assert.equal(formatFileSize(1073741824), "1.0 GB");
});

test("shortHash 截断显示", () => {
  assert.equal(shortHash(""), "—");
  assert.equal(shortHash(null), "—");
  assert.equal(shortHash("abcdef1234567890"), "abcdef123456…");
});

test("hasBothReportAssets 和 missingReportAssets 完整性判断", () => {
  assert.equal(hasBothReportAssets([{ asset_type: "markdown" }, { asset_type: "pdf" }]), true);
  assert.equal(hasBothReportAssets([{ asset_type: "markdown" }]), false);
  assert.equal(hasBothReportAssets([]), false);
  assert.deepEqual(missingReportAssets([{ asset_type: "markdown" }]), ["pdf"]);
  assert.deepEqual(missingReportAssets([]), ["markdown", "pdf"]);
  assert.deepEqual(missingReportAssets([{ asset_type: "markdown" }, { asset_type: "pdf" }]), []);
});

test("REPORT_STATUS 和 REPORT_WARNING_CODES 状态映射正确", () => {
  assert.deepEqual(REPORT_STATUS.ready, ["质量门通过", "success"]);
  assert.deepEqual(REPORT_STATUS.ready_with_warnings, ["需人工复核", "warning"]);
  assert.deepEqual(REPORT_STATUS.unknown_key, undefined);
  assert.ok(REPORT_WARNING_CODES.REVIEW_REPORT_PENDING_REVIEW.includes("待人工复核"));
  assert.ok(REPORT_WARNING_CODES.REVIEW_REPORT_HIGH_RISK_UNREVIEWED.includes("高风险"));
  // 未知 warning 回退
  assert.equal(REPORT_WARNING_CODES.UNKNOWN, undefined);
});

// ── 智能核验工具函数（阶段 4C-3）──────────────────────────────────────

test("describePlanner 三态语义：只有 deepseek+无 fallback 才算模型规划成功", () => {
  assert.deepEqual(
    describePlanner({ planner_type: "deepseek", fallback_used: false }),
    { label: "DeepSeek 规划成功", tone: "success" },
  );
  // fallback 不得包装成模型成功
  assert.deepEqual(
    describePlanner({ planner_type: "deterministic_fallback", fallback_used: true }),
    { label: "DeepSeek 输出未通过校验，已使用确定性计划", tone: "warning" },
  );
  assert.deepEqual(
    describePlanner({ planner_type: "deterministic", fallback_used: false }),
    { label: "确定性规划", tone: "neutral" },
  );
  // 防御：planner_type=deepseek 但 fallback_used=true 不能显示为成功
  assert.notEqual(
    describePlanner({ planner_type: "deepseek", fallback_used: true }).tone,
    "success",
  );
});

test("normalizePlanDecisions 同时保留 retrieve 与 skip，skip 带原因且无 query", () => {
  const plan = {
    decisions: [
      { finding_id: 1, issue_code: "SYN-EQ-001", decision: "retrieve", reason: "补充检索", query: "证书编号", retrieval_mode: "hybrid_rrf", top_k: 5 },
      { finding_id: 2, issue_code: "SYN-REQ-001", decision: "skip", reason: "已有足够证据", query: null },
    ],
  };
  const items = normalizePlanDecisions(plan);
  assert.equal(items.length, 2);
  assert.equal(items[0].decision, "retrieve");
  assert.equal(items[0].query, "证书编号");
  assert.equal(items[1].decision, "skip");
  assert.equal(items[1].query, null);
  assert.ok(items[1].reason);
  assert.deepEqual(normalizePlanDecisions(null), []);
});

test("sortToolCallsByTime 按 id 升序且不合并 retry 链", () => {
  const calls = [
    { id: 3, tool_name: "engineering_hybrid_retrieval", attempt_number: 2, retry_of_id: 1, status: "success" },
    { id: 1, tool_name: "engineering_hybrid_retrieval", attempt_number: 1, status: "failed" },
    { id: 2, tool_name: "engineering_retrieval_index_prepare", attempt_number: 1, status: "success" },
  ];
  const sorted = sortToolCallsByTime(calls);
  assert.deepEqual(sorted.map((c) => c.id), [1, 2, 3]);
  // prepare、失败 attempt、成功 retry 三条都保留
  assert.equal(sorted.length, 3);
  assert.equal(sorted[2].retry_of_id, 1);
});

test("formatCandidateLocator 三类定位格式", () => {
  assert.equal(formatCandidateLocator({ locator_type: "pdf_page", page_number: 3 }), "第 3 页");
  assert.equal(
    formatCandidateLocator({ locator_type: "spreadsheet_cell", sheet_name: "人员表", cell_range: "B2" }),
    "人员表!B2",
  );
  assert.equal(formatCandidateLocator({ locator_type: "text_chunk" }), "文本块");
  assert.equal(formatCandidateLocator(null), "—");
});

test("groupCandidatesByFinding 按 Finding 分组且组内稳定排序", () => {
  const candidates = [
    { finding_id: 2, issue_code: "B", tool_call_id: 5, candidate_rank: 2 },
    { finding_id: 1, issue_code: "A", tool_call_id: 4, candidate_rank: 2 },
    { finding_id: 1, issue_code: "A", tool_call_id: 4, candidate_rank: 1 },
    { finding_id: 2, issue_code: "B", tool_call_id: 5, candidate_rank: 1 },
  ];
  const groups = groupCandidatesByFinding(candidates);
  assert.equal(groups.length, 2);
  const groupA = groups.find((g) => g.issueCode === "A");
  assert.deepEqual(groupA.candidates.map((c) => c.candidate_rank), [1, 2]);
  const groupB = groups.find((g) => g.issueCode === "B");
  assert.deepEqual(groupB.candidates.map((c) => c.candidate_rank), [1, 2]);
});

test("getCandidateErrorSuggestion 覆盖 stale 与 conflict 恢复建议", () => {
  assert.ok(getCandidateErrorSuggestion("VERIFICATION_CANDIDATE_STALE").includes("过期"));
  assert.ok(getCandidateErrorSuggestion("VERIFICATION_CANDIDATE_DECISION_CONFLICT").includes("不可更改"));
  assert.ok(getCandidateErrorSuggestion("VERIFICATION_RUN_NOT_COMPLETED").includes("尚未完成"));
  assert.equal(getCandidateErrorSuggestion("UNKNOWN"), "请按错误信息修正后重试。");
});
