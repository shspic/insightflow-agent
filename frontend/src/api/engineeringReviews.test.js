import assert from "node:assert/strict";
import test from "node:test";

import {
  confirmReviewBrief,
  createReviewBrief,
  createReviewFindingAction,
  createReviewRun,
  createSupervisorRun,
  createVerificationCandidateDecision,
  createVerificationRun,
  downloadReviewReportAsset,
  executeReviewRun,
  fetchCurrentReviewBrief,
  fetchReviewBrief,
  fetchReviewEvidences,
  fetchReviewFindingActions,
  fetchReviewFindings,
  fetchReviewReport,
  fetchReviewReportAssets,
  fetchReviewReports,
  fetchReviewRun,
  fetchReviewRuns,
  fetchSupervisorRun,
  fetchSupervisorRuns,
  fetchSupervisorSteps,
  fetchVerificationCandidateDecisions,
  fetchVerificationCandidates,
  fetchVerificationRun,
  fetchVerificationRuns,
  fetchVerificationToolCalls,
  generateReviewReport,
} from "./engineeringReviews.js";
import { resetCsrfToken } from "./client.js";

function jsonResponse(status, data) {
  return { ok: status >= 200 && status < 300, status, json: async () => data };
}

test.beforeEach(() => {
  resetCsrfToken();
  globalThis.window = { dispatchEvent() {}, setTimeout: (fn) => fn?.() };
  globalThis.CustomEvent = class { constructor(type) { this.type = type; } };
});

test.afterEach(() => {
  resetCsrfToken();
  delete globalThis.fetch;
  delete globalThis.window;
  delete globalThis.CustomEvent;
});

test("工程审查 API 使用统一路径、method 和 payload", async () => {
  const requests = [];
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url, options });
    if (url.endsWith("/auth/csrf")) return jsonResponse(200, { csrf_token: "review-token" });
    return jsonResponse(200, { ok: true });
  };

  const briefPayload = { raw_requirements: "要求", interpreter_type: "manual", interpreted: {} };
  const runPayload = { review_brief_id: 8, review_template_key: "engineering_bid_review_v1" };
  const actionPayload = { action_type: "confirm", review_note: "已核对" };
  await createReviewBrief(7, briefPayload);
  await fetchCurrentReviewBrief(7);
  await fetchReviewBrief(7, 8);
  await confirmReviewBrief(7, 8);
  await createReviewRun(7, runPayload);
  await fetchReviewRuns(7);
  await fetchReviewRun(7, 9);
  await executeReviewRun(7, 9);
  await fetchReviewEvidences(7, 9);
  await fetchReviewFindings(7, 9);
  await createReviewFindingAction(7, 10, actionPayload);
  await fetchReviewFindingActions(7, 10);

  const actual = requests.filter((item) => !item.url.endsWith("/auth/csrf")).map((item) => ({
    path: item.url.replace("/api/v2", ""),
    method: item.options.method || "GET",
    body: item.options.body ? JSON.parse(item.options.body) : undefined,
  }));
  assert.deepEqual(actual, [
    { path: "/workspaces/7/review-briefs", method: "POST", body: briefPayload },
    { path: "/workspaces/7/review-briefs/current", method: "GET", body: undefined },
    { path: "/workspaces/7/review-briefs/8", method: "GET", body: undefined },
    { path: "/workspaces/7/review-briefs/8/confirm", method: "POST", body: undefined },
    { path: "/workspaces/7/review-runs", method: "POST", body: runPayload },
    { path: "/workspaces/7/review-runs", method: "GET", body: undefined },
    { path: "/workspaces/7/review-runs/9", method: "GET", body: undefined },
    { path: "/workspaces/7/review-runs/9/execute", method: "POST", body: undefined },
    { path: "/workspaces/7/review-runs/9/evidences", method: "GET", body: undefined },
    { path: "/workspaces/7/review-runs/9/findings", method: "GET", body: undefined },
    { path: "/workspaces/7/review-findings/10/actions", method: "POST", body: actionPayload },
    { path: "/workspaces/7/review-findings/10/actions", method: "GET", body: undefined },
  ]);
});

test("detail.error_code 被 ApiError 正确识别", async () => {
  globalThis.fetch = async () => jsonResponse(422, {
    detail: { error_code: "REVIEW_MATERIAL_MISSING", message: "缺少已确认角色" },
  });
  await assert.rejects(
    fetchReviewRun(3, 4),
    (error) => error.status === 422
      && error.code === "REVIEW_MATERIAL_MISSING"
      && error.message === "缺少已确认角色",
  );
});

// ── ReviewReport API 测试 ───────────────────────────────────────────

test("generateReviewReport POST 路径和 method 正确", async () => {
  const requests = [];
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url, method: options.method, body: options.body });
    if (url.endsWith("/auth/csrf")) return jsonResponse(200, { csrf_token: "t" });
    return jsonResponse(201, { id: 1, version: 1 });
  };
  await generateReviewReport(7, 9);
  const actual = requests.filter((item) => !item.url.endsWith("/auth/csrf")).map((item) => ({
    path: item.url.replace("/api/v2", ""),
    method: item.method,
  }));
  assert.deepEqual(actual, [
    { path: "/workspaces/7/review-runs/9/reports", method: "POST" },
  ]);
});

test("fetchReviewReports GET 列表路径正确", async () => {
  globalThis.fetch = async (url) => jsonResponse(200, [{ id: 1, version: 1 }, { id: 2, version: 2 }]);
  const data = await fetchReviewReports(7, 9);
  assert.equal(data.length, 2);
});

test("fetchReviewReport GET 指定版本路径正确", async () => {
  globalThis.fetch = async (url) => {
    assert.ok(url.includes("/workspaces/7/review-runs/9/reports/5"));
    return jsonResponse(200, { id: 5, version: 3 });
  };
  const data = await fetchReviewReport(7, 9, 5);
  assert.equal(data.id, 5);
});

test("fetchReviewReportAssets GET 资产列表路径正确", async () => {
  globalThis.fetch = async (url) => {
    assert.ok(url.includes("/workspaces/7/review-runs/9/reports/5/assets"));
    return jsonResponse(200, [{ id: 10, asset_type: "markdown" }]);
  };
  const data = await fetchReviewReportAssets(7, 9, 5);
  assert.equal(data.length, 1);
  assert.equal(data[0].asset_type, "markdown");
});

test("downloadReviewReportAsset 路径严格为 /api/v2/.../download，credentials include 且 revoke 被调用", async () => {
  let capturedPath = null;
  let capturedOptions = null;
  let revokeCalls = 0;
  const revokedUrls = [];
  globalThis.fetch = async (url, options) => {
    capturedPath = url;
    capturedOptions = options;
    return {
      ok: true,
      blob: async () => new Blob(["test"]),
      headers: new Headers({ "content-disposition": "attachment; filename=\"report-1-v1.pdf\"" }),
    };
  };
  globalThis.URL = {
    createObjectURL: () => "blob:test-url",
    revokeObjectURL: (u) => { revokeCalls++; revokedUrls.push(u); },
  };
  function makeAnchor() {
    let storedDownload = "";
    return {
      set href(v) {},
      get download() { return storedDownload; },
      set download(v) { storedDownload = v; },
      click() {},
      remove() {},
    };
  }
  globalThis.document = {
    body: { appendChild() {}, removeChild() {} },
    createElement: () => makeAnchor(),
  };
  try {
    await downloadReviewReportAsset(7, 9, 5, 10, "fallback-name");
    assert.strictEqual(capturedPath, "/api/v2/workspaces/7/review-runs/9/reports/5/assets/10/download",
      `路径必须严格等于 /api/v2/.../download，实际: ${capturedPath}`);
    assert.strictEqual(capturedOptions?.credentials, "include", "下载请求必须携带 credentials");
    assert.strictEqual(revokeCalls, 1, "URL.revokeObjectURL 应被调用一次");
    assert.ok(revokedUrls.includes("blob:test-url"), "应 revoke 创建的 blob URL");
  } finally {
    delete globalThis.document;
    delete globalThis.URL;
  }
});

test("downloadReviewReportAsset fallback 文件名：无 content-disposition 时使用传入参数", async () => {
  let capturedDownload = null;
  globalThis.fetch = async () => ({
    ok: true,
    blob: async () => new Blob(),
    headers: new Headers({}),
  });
  globalThis.URL = { createObjectURL: () => "blob:test", revokeObjectURL: () => {} };
  function makeAnchor() {
    let storedDownload = "";
    return {
      set href(v) {},
      get download() { return storedDownload; },
      set download(v) { storedDownload = v; },
      click() {},
      remove() {},
    };
  }
  globalThis.document = {
    body: {
      appendChild(el) { capturedDownload = el.download; },
      removeChild() {},
    },
    createElement: () => makeAnchor(),
  };
  try {
    await downloadReviewReportAsset(7, 9, 5, 10, "custom-fallback.bin");
    assert.strictEqual(capturedDownload, "custom-fallback.bin",
      `无 content-disposition 时应使用 fallback，实际: ${capturedDownload}`);
  } finally {
    delete globalThis.document;
    delete globalThis.URL;
  }
});

test("downloadReviewReportAsset 响应文件名优先于 fallback", async () => {
  let capturedDownloads = [];
  globalThis.fetch = async () => ({
    ok: true,
    blob: async () => new Blob(),
    headers: new Headers({ "content-disposition": "attachment; filename=\"server-name.pdf\"" }),
  });
  globalThis.URL = { createObjectURL: () => "blob:test", revokeObjectURL: () => {} };
  function makeAnchor() {
    let storedDownload = "";
    return {
      set href(v) {},
      get download() { return storedDownload; },
      set download(v) { storedDownload = v; },
      click() {},
      remove() {},
    };
  }
  globalThis.document = {
    body: {
      appendChild(el) { capturedDownloads.push(el.download); },
      removeChild() {},
    },
    createElement: () => makeAnchor(),
  };
  try {
    await downloadReviewReportAsset(7, 9, 5, 10, "fallback-should-not-be-used.pdf");
    // 下载的 filename 应使用服务器响应中的文件名
    assert.ok(capturedDownloads.includes("server-name.pdf"),
      `响应文件名 server-name.pdf 应优先于 fallback，实际 downloads: ${JSON.stringify(capturedDownloads)}`);
    assert.ok(!capturedDownloads.some((d) => d === "fallback-should-not-be-used.pdf"),
      "fallback 不应出现在文件名中");
  } finally {
    delete globalThis.document;
    delete globalThis.URL;
  }
});

test("generateReviewReport reused=true 原样返回", async () => {
  globalThis.fetch = async (url) => {
    if (url.endsWith("/auth/csrf")) return jsonResponse(200, { csrf_token: "t" });
    return jsonResponse(200, { id: 2, version: 1, reused: true });
  };
  const result = await generateReviewReport(7, 9);
  assert.strictEqual(result.reused, true);
  assert.strictEqual(result.version, 1);
});

test("generateReviewReport reused=false 原样返回", async () => {
  globalThis.fetch = async (url) => {
    if (url.endsWith("/auth/csrf")) return jsonResponse(200, { csrf_token: "t" });
    return jsonResponse(201, { id: 3, version: 2, reused: false });
  };
  const result = await generateReviewReport(7, 9);
  assert.strictEqual(result.reused, false);
  assert.strictEqual(result.version, 2);
});

test("后端 detail.error_code 在报告 API 中透传", async () => {
  globalThis.fetch = async (url) => {
    if (url.endsWith("/auth/csrf")) return jsonResponse(200, { csrf_token: "t" });
    return jsonResponse(409, {
      detail: { error_code: "REVIEW_REPORT_RUN_NOT_COMPLETED", message: "Run 尚未完成" },
    });
  };
  await assert.rejects(
    generateReviewReport(7, 9),
    (error) => error.status === 409
      && error.code === "REVIEW_REPORT_RUN_NOT_COMPLETED"
      && error.message === "Run 尚未完成",
  );
});

// ── 智能核验 API（阶段 4C-3）──────────────────────────────────────────

test("智能核验七个 API client 的 method/path/body", async () => {
  const requests = [];
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url, options });
    if (url.endsWith("/auth/csrf")) return jsonResponse(200, { csrf_token: "v-token" });
    return jsonResponse(200, { ok: true });
  };

  const launchPayload = { use_deepseek: true, max_tool_calls: 3 };
  const decisionPayload = { tool_call_id: 11, candidate_rank: 2, decision: "accept", review_note: "已核对" };
  await createVerificationRun(7, 9, launchPayload);
  await fetchVerificationRuns(7, 9);
  await fetchVerificationRun(7, 9, 21);
  await fetchVerificationToolCalls(7, 9, 21);
  await fetchVerificationCandidates(7, 9, 21);
  await createVerificationCandidateDecision(7, 9, 21, decisionPayload);
  await fetchVerificationCandidateDecisions(7, 9, 21);

  const base = "/api/v2/workspaces/7/review-runs/9/verification-runs";
  assert.deepStrictEqual(requests.map((r) => [r.options.method || "GET", r.url]), [
    ["GET", "/api/v2/auth/csrf"],
    ["POST", base],
    ["GET", base],
    ["GET", base + "/21"],
    ["GET", base + "/21/tool-calls"],
    ["GET", base + "/21/candidates"],
    ["POST", base + "/21/candidate-decisions"],
    ["GET", base + "/21/candidate-decisions"],
  ]);
  assert.deepStrictEqual(JSON.parse(requests[1].options.body), launchPayload);
  assert.deepStrictEqual(JSON.parse(requests[6].options.body), decisionPayload);
});

test("createVerificationRun 透传 201 reused=false 与 200 reused=true", async () => {
  globalThis.fetch = async (url) => {
    if (url.endsWith("/auth/csrf")) return jsonResponse(200, { csrf_token: "t" });
    return jsonResponse(201, { verification_run_id: 5, reused: false });
  };
  const created = await createVerificationRun(7, 9, { use_deepseek: false, max_tool_calls: 5 });
  assert.strictEqual(created.reused, false);

  globalThis.fetch = async (url) => {
    if (url.endsWith("/auth/csrf")) return jsonResponse(200, { csrf_token: "t" });
    return jsonResponse(200, { verification_run_id: 5, reused: true });
  };
  const reusedResult = await createVerificationRun(7, 9, { use_deepseek: false, max_tool_calls: 5 });
  assert.strictEqual(reusedResult.reused, true);
});

test("createVerificationCandidateDecision 透传 201/200/409 语义", async () => {
  globalThis.fetch = async (url) => {
    if (url.endsWith("/auth/csrf")) return jsonResponse(200, { csrf_token: "t" });
    return jsonResponse(201, { id: 1, decision: "accept", reused: false, evidence_id: 33 });
  };
  const accepted = await createVerificationCandidateDecision(7, 9, 21, {
    tool_call_id: 11, candidate_rank: 1, decision: "accept",
  });
  assert.strictEqual(accepted.reused, false);
  assert.strictEqual(accepted.evidence_id, 33);

  globalThis.fetch = async (url) => {
    if (url.endsWith("/auth/csrf")) return jsonResponse(200, { csrf_token: "t" });
    return jsonResponse(200, { id: 1, decision: "accept", reused: true });
  };
  const repeated = await createVerificationCandidateDecision(7, 9, 21, {
    tool_call_id: 11, candidate_rank: 1, decision: "accept",
  });
  assert.strictEqual(repeated.reused, true);

  globalThis.fetch = async (url) => {
    if (url.endsWith("/auth/csrf")) return jsonResponse(200, { csrf_token: "t" });
    return jsonResponse(409, {
      detail: { error_code: "VERIFICATION_CANDIDATE_DECISION_CONFLICT", message: "已有相反决策" },
    });
  };
  await assert.rejects(
    createVerificationCandidateDecision(7, 9, 21, {
      tool_call_id: 11, candidate_rank: 1, decision: "reject",
    }),
    (error) => error.status === 409 && error.code === "VERIFICATION_CANDIDATE_DECISION_CONFLICT",
  );
});

// ── Engineering Supervisor API（阶段 5B）────────────────────────────

test("Supervisor 四个 API client 的 method/path/body", async () => {
  const requests = [];
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url, options });
    if (url.endsWith("/auth/csrf")) return jsonResponse(200, { csrf_token: "v-token" });
    return jsonResponse(200, { ok: true });
  };

  const payload = {
    use_deepseek: true,
    max_verification_tool_calls: 4,
    max_step_retries: 2,
    generate_report: true,
  };
  await createSupervisorRun(7, 9, payload);
  await fetchSupervisorRuns(7, 9);
  await fetchSupervisorRun(7, 9, 31);
  await fetchSupervisorSteps(7, 9, 31);

  const base = "/api/v2/workspaces/7/review-runs/9/supervisor-runs";
  assert.deepStrictEqual(requests.map((r) => [r.options.method || "GET", r.url]), [
    ["GET", "/api/v2/auth/csrf"],
    ["POST", base],
    ["GET", base],
    ["GET", base + "/31"],
    ["GET", base + "/31/steps"],
  ]);
  assert.deepStrictEqual(JSON.parse(requests[1].options.body), payload);
});

test("createSupervisorRun 透传 201 reused=false 与 200 reused=true", async () => {
  globalThis.fetch = async (url) => {
    if (url.endsWith("/auth/csrf")) return jsonResponse(200, { csrf_token: "t" });
    return jsonResponse(201, { supervisor_run_id: 8, reused: false, status: "ready_to_report" });
  };
  const created = await createSupervisorRun(7, 9, { use_deepseek: false, generate_report: false });
  assert.strictEqual(created.reused, false);
  assert.strictEqual(created.supervisor_run_id, 8);

  globalThis.fetch = async (url) => {
    if (url.endsWith("/auth/csrf")) return jsonResponse(200, { csrf_token: "t" });
    return jsonResponse(200, { supervisor_run_id: 8, reused: true, status: "ready_to_report" });
  };
  const reusedResult = await createSupervisorRun(7, 9, { use_deepseek: false, generate_report: false });
  assert.strictEqual(reusedResult.reused, true);
  assert.strictEqual(reusedResult.supervisor_run_id, 8);
});

test("Supervisor API 错误透传 error_code/message", async () => {
  globalThis.fetch = async (url) => {
    if (url.endsWith("/auth/csrf")) return jsonResponse(200, { csrf_token: "t" });
    return jsonResponse(422, {
      detail: { error_code: "SUPERVISOR_RUN_NOT_COMPLETED", message: "ReviewRun 必须为 completed" },
    });
  };
  await assert.rejects(
    createSupervisorRun(7, 9, { use_deepseek: false }),
    (error) => error.status === 422 && error.code === "SUPERVISOR_RUN_NOT_COMPLETED",
  );
});
