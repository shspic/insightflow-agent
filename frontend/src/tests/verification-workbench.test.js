// 阶段 4C-3：智能核验工作台的静态约束测试。
// 不引入组件测试框架，直接对源码做契约断言（与后端 test_no_ground_truth_usage 同模式）。

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { resolvePageTitle } from "../utils/ui.js";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

function readSource(relativePath) {
  return readFileSync(join(SRC, relativePath), "utf-8");
}

test("engineering 项目详情页包含智能核验入口，路由段为 verification", () => {
  const source = readSource("pages/EngineeringProjectDetail.jsx");
  assert.ok(source.includes("智能核验"), "缺少智能核验导航");
  assert.ok(source.includes('"verification"'), "缺少 verification section");
  assert.ok(source.includes("VerificationPanel"), "未挂载 VerificationPanel");
});

test("general 区域完全不引入智能核验", () => {
  const workspaceDetail = readSource("pages/WorkspaceDetail.jsx");
  assert.ok(!workspaceDetail.includes("VerificationPanel"), "general 页面不得引入 VerificationPanel");
  assert.ok(!workspaceDetail.includes("智能核验"), "general 页面不得出现智能核验入口");
  const appLayout = readSource("components/AppLayout.jsx");
  assert.ok(!appLayout.includes("VerificationPanel"), "布局不得引入 VerificationPanel");
});

test("VerificationPanel 不读取 ground_truth、不使用 window.open、不自动生成报告", () => {
  const source = readSource("components/engineering/VerificationPanel.jsx");
  assert.ok(!source.includes("ground_truth"), "不得读取黄金答案");
  assert.ok(!source.includes("window.open"), "不得使用 window.open");
  assert.ok(!source.includes("generateReviewReport"), "不得自动生成报告");
  assert.ok(!source.includes("createReviewFindingAction"), "不得自动修改 Finding 状态");
});

test("VerificationPanel 不会在页面加载后自动启动核验", () => {
  const source = readSource("components/engineering/VerificationPanel.jsx");
  // createVerificationRun 只允许出现在用户点击触发的 launchVerification 中
  const occurrences = source.split("createVerificationRun(").length - 1;
  assert.equal(occurrences, 1, "启动核验只能有一个调用点（用户点击）");
  const useEffectBlocks = source.match(/useEffect\([\s\S]*?\}\s*,\s*\[[^\]]*\]\s*\)/g) || [];
  for (const block of useEffectBlocks) {
    assert.ok(!block.includes("createVerificationRun"), "useEffect 中不得启动核验");
    assert.ok(!block.includes("createVerificationCandidateDecision"), "useEffect 中不得自动决策");
  }
});

test("智能核验路由标题", () => {
  assert.equal(
    resolvePageTitle("/engineering/projects/12/verification"),
    "智能核验 · InsightFlow Agent",
  );
});

test("候选证据边界说明固定展示", () => {
  const source = readSource("components/engineering/VerificationPanel.jsx");
  assert.ok(source.includes("检索结果只是候选证据"), "缺少候选边界说明");
  assert.ok(source.includes("接受候选不会自动确认问题、降低风险或修改结论"), "缺少边界说明第二句");
});

test("MCP 工具中文名称展示", () => {
  const source = readSource("components/engineering/VerificationPanel.jsx");
  assert.ok(source.includes('search_review_rules: "MCP 规则检索"'), "缺少 search_review_rules 中文名");
  assert.ok(source.includes('run_bid_consistency_checks: "MCP 一致性检查"'), "缺少 run_bid_consistency_checks 中文名");
});

test("检索/MCP/总调用数分离展示", () => {
  const source = readSource("components/engineering/VerificationPanel.jsx");
  assert.ok(source.includes("检索预算"), "缺少检索预算展示");
  assert.ok(source.includes("MCP 调用"), "缺少 MCP 调用数展示");
  assert.ok(source.includes("总调用"), "缺少总调用数展示");
  assert.ok(source.includes("retrieval_tool_call_count"), "缺少检索调用计数字段");
  assert.ok(source.includes("mcp_tool_call_count"), "缺少 MCP 调用计数字段");
});

test("MCP retry 链逐行展示不合并", () => {
  const source = readSource("components/engineering/VerificationPanel.jsx");
  assert.ok(source.includes("attempt_number"), "工具表保留 attempt 列");
  assert.ok(source.includes("retry_of_id"), "工具表保留 retry_of 列");
});

test("MCP 关闭时不显示伪成功", () => {
  const source = readSource("components/engineering/VerificationPanel.jsx");
  assert.ok(source.includes("MCP 未启用：未执行 MCP 核验"), "缺少 MCP 关闭提示");
  assert.ok(!source.includes("已使用 MCP") && !source.includes("MCP 已连接"), "不得显示 MCP 已使用");
});

test("general 页面不引入 Verification MCP", () => {
  const detail = readSource("pages/WorkspaceDetail.jsx");
  assert.ok(!detail.includes("VerificationPanel"), "general 页面不得引入 VerificationPanel");
});

test("MCP 警告展示与恢复建议", () => {
  const source = readSource("components/engineering/VerificationPanel.jsx");
  assert.ok(source.includes("ENGINEERING_MCP_UNAVAILABLE"), "缺少 UNAVAILABLE 错误提示");
  assert.ok(source.includes("ENGINEERING_MCP_TIMEOUT"), "缺少 TIMEOUT 错误提示");
  assert.ok(source.includes("ENGINEERING_MCP_DISCOVERY_ERROR"), "缺少 DISCOVERY 错误提示");
  assert.ok(source.includes("核验上下文不完整"), "缺少核验上下文不完整提示");
  assert.ok(source.includes("可稍后重试"), "缺少恢复建议");
});

test("核验详情遍历 detail.warnings 独立展示", () => {
  const source = readSource("components/engineering/VerificationPanel.jsx");
  assert.ok(source.includes("detail.warnings"), "组件必须读取 detail.warnings");
  assert.ok(source.includes("detail.warnings.map"), "组件必须遍历 detail.warnings");
  assert.ok(source.includes("detail.warnings.length > 0"), "warnings 为空时不渲染");
  assert.ok(source.includes("核验警告"), "独立警告区标题");
});
