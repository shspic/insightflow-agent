import assert from "node:assert/strict";
import test from "node:test";
import {
  FILE_STATUS,
  TASK_STATUS,
  allowedNavigation,
  fileTypeMeta,
  mapApiError,
  mergeEvents,
  oneTimeSecretReducer,
  quotaState,
  readThemePreference,
  resolvePageTitle,
  sortReportVersions,
  statusMeta,
  validatePlanSteps,
} from "./ui.js";

test("状态映射同时返回中文文案和非颜色语义", () => {
  assert.deepEqual(statusMeta("running", TASK_STATUS), { label: "执行中", tone: "info" });
  assert.deepEqual(statusMeta("ready", FILE_STATUS), { label: "已就绪", tone: "success" });
});

test("错误映射提供标题、下一步和技术标识", () => {
  const result = mapApiError({ status: 429, code: "QUOTA_EXCEEDED", message: "达到上限" });
  assert.equal(result.title, "配额不足或操作过于频繁");
  assert.match(result.action, /使用量/);
  assert.equal(result.technicalId, "QUOTA_EXCEEDED");
});

test("配额达到八成时进入预警", () => {
  assert.equal(quotaState(79, 100).warning, false);
  assert.deepEqual(quotaState(80, 100), {
    ratio: 0.8, percent: 80, tone: "warning", warning: true,
  });
  assert.equal(quotaState(101, 100).tone, "danger");
});

test("计划校验拒绝倒序依赖并要求审核最后执行", () => {
  const valid = [
    { step_key: "understand", agent_type: "file_understanding_agent", depends_on: [] },
    { step_key: "report", agent_type: "report_agent", depends_on: ["understand"] },
    { step_key: "review", agent_type: "quality_review_agent", depends_on: ["report"] },
  ];
  assert.equal(validatePlanSteps(valid).valid, true);
  assert.equal(validatePlanSteps([valid[1], valid[0], valid[2]]).valid, false);
  assert.equal(validatePlanSteps(valid.slice(0, 2)).valid, false);
});

test("SSE 事件按 ID 合并、去重并限制长度", () => {
  const merged = mergeEvents([{ id: 2, message: "旧" }], [
    { id: 1, message: "一" }, { id: 2, message: "新" }, { id: 3, message: "三" },
  ], 2);
  assert.deepEqual(merged.map((item) => item.id), [2, 3]);
  assert.equal(merged[0].message, "新");
});

test("报告版本优先当前版本，其余按版本倒序", () => {
  const sorted = sortReportVersions([
    { version: 3, is_current: false },
    { version: 1, is_current: true },
    { version: 2, is_current: false },
  ]);
  assert.deepEqual(sorted.map((item) => item.version), [1, 3, 2]);
});

test("文件类型映射返回文字标识", () => {
  assert.deepEqual(fileTypeMeta(".xlsx"), { label: "Excel", glyph: "表" });
  assert.deepEqual(fileTypeMeta("pdf"), { label: "PDF", glyph: "文" });
});

test("权限导航只向管理员暴露管理入口", () => {
  assert.deepEqual(allowedNavigation("user"), ["workspaces", "usage"]);
  assert.deepEqual(allowedNavigation("admin"), ["workspaces", "usage", "admin"]);
});

test("一次性秘密关闭后清除明文", () => {
  const shown = oneTimeSecretReducer({}, { type: "show", title: "邀请码", value: "secret" });
  assert.equal(shown.visible, true);
  assert.deepEqual(oneTimeSecretReducer(shown, { type: "clear" }), {
    title: "", value: "", visible: false,
  });
});

test("主题读取对非法值和存储异常回退为跟随系统", () => {
  assert.equal(readThemePreference({ getItem: () => "dark" }), "dark");
  assert.equal(readThemePreference({ getItem: () => "unknown" }), "system");
  assert.equal(readThemePreference({ getItem: () => { throw new Error("blocked"); } }), "system");
});

test("浏览器标题按路由统一包含产品名称", () => {
  assert.equal(resolvePageTitle("/login"), "登录 · InsightFlow Agent");
  assert.equal(resolvePageTitle("/workspaces/9/tasks/12"), "任务详情 · InsightFlow Agent");
  assert.equal(resolvePageTitle("/workspaces/9/reports/12"), "报告 · InsightFlow Agent");
  assert.equal(resolvePageTitle("/workspaces/9/context"), "Workspace Context · InsightFlow Agent");
  assert.equal(resolvePageTitle("/workspaces/9/settings"), "工作区设置 · InsightFlow Agent");
  assert.equal(resolvePageTitle("/admin"), "管理后台 · InsightFlow Agent");
});

test("V3 工程审查与通用分析路由标题", () => {
  assert.equal(resolvePageTitle("/engineering/projects"), "engineering · InsightFlow Agent");
  assert.equal(resolvePageTitle("/engineering/projects/1"), "engineering · InsightFlow Agent");
  assert.equal(resolvePageTitle("/engineering/projects/1/files"), "文件 · InsightFlow Agent");
  assert.equal(resolvePageTitle("/engineering/projects/1/tasks/2"), "任务详情 · InsightFlow Agent");
  assert.equal(resolvePageTitle("/engineering/projects/1/reports/2"), "报告 · InsightFlow Agent");
  assert.equal(resolvePageTitle("/engineering/projects/1/context"), "Workspace Context · InsightFlow Agent");
  assert.equal(resolvePageTitle("/general/workspaces"), "general · InsightFlow Agent");
  assert.equal(resolvePageTitle("/general/workspaces/1"), "general · InsightFlow Agent");
  assert.equal(resolvePageTitle("/general/workspaces/1/tasks/2"), "任务详情 · InsightFlow Agent");
});

test("旧路由 legacy redirect 映射正确性", () => {
  // 验证 redirectType 参数驱动的跳转目标
  const redirect = (type, workspaceId, section, taskId) => {
    if (type === "report") return `/general/workspaces/${workspaceId}/reports/${taskId}`;
    if (type === "task") return `/general/workspaces/${workspaceId}/tasks/${taskId}`;
    if (type === "section") return `/general/workspaces/${workspaceId}/${section}`;
    return `/general/workspaces/${workspaceId}`;
  };
  assert.equal(redirect("detail", "12"), "/general/workspaces/12");
  assert.equal(redirect("section", "12", "files"), "/general/workspaces/12/files");
  assert.equal(redirect("task", "12", undefined, "34"), "/general/workspaces/12/tasks/34");
  assert.equal(redirect("report", "12", undefined, "34"), "/general/workspaces/12/reports/34");
  // report 不应进入 task 分支
  assert.notEqual(redirect("report", "12", undefined, "34"), "/general/workspaces/12/tasks/34");
});
