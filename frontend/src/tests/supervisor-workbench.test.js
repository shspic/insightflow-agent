// 阶段 5B：Supervisor 工作台静态约束测试。
// 不引入组件测试框架，直接对源码做契约断言（与 verification-workbench 同模式）。

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

function readSource(relativePath) {
  return readFileSync(join(SRC, relativePath), "utf-8");
}

test("智能核验页面包含 Supervisor 启动入口与全部配置项", () => {
  const source = readSource("components/engineering/VerificationPanel.jsx");
  assert.ok(source.includes("启动 Supervisor"), "缺少启动 Supervisor 按钮");
  assert.ok(source.includes("createSupervisorRun"), "缺少 Supervisor 启动调用");
  assert.ok(source.includes("useDeepseek") && source.includes("DeepSeek 规划"), "缺少 DeepSeek 开关");
  assert.ok(source.includes("maxVerificationToolCalls") && source.includes("Verification 预算"), "缺少 Verification 预算");
  assert.ok(source.includes("maxStepRetries") && source.includes("最大重试次数"), "缺少最大重试次数");
  assert.ok(source.includes("generateReport") && source.includes("generate_report"), "缺少 generate_report 开关");
});

test("Supervisor 历史与详情字段完整", () => {
  const source = readSource("components/engineering/VerificationPanel.jsx");
  assert.ok(source.includes("Supervisor 历史"), "缺少 Supervisor 历史");
  assert.ok(source.includes("supervisor_run_id"), "缺少 supervisor_run_id");
  assert.ok(source.includes("四节点时间线"), "缺少四节点时间线");
  assert.ok(source.includes("SUPERVISOR_NODE_LABELS") || source.includes("normalizeSupervisorTimeline"), "缺少节点工具");
  assert.ok(source.includes("attempt_number") && source.includes("retry_of_id"), "缺少 attempt/retry_of");
  assert.ok(source.includes('step.reused') && source.includes('step.latency_ms'), "缺少 reused/latency");
  assert.ok(source.includes("step.error_code") && source.includes("step.error_message"), "缺少步骤错误信息");
});

test("Quality Review 检查项与质量门结论展示", () => {
  const source = readSource("components/engineering/VerificationPanel.jsx");
  assert.ok(source.includes("Quality Review 检查项"), "缺少检查项区块");
  assert.ok(source.includes("reportable_finding_ids") && source.includes("reportable Finding"), "缺少 reportable Finding");
  assert.ok(source.includes("need_more_information_finding_ids"), "缺少 need_more_information");
  assert.ok(source.includes("related_file_ids"), "缺少 related file ids");
  assert.ok(source.includes("GATE_CHECK_CODE_LABELS"), "缺少检查码说明");
});

test("clarification、needs_human 原因与恢复建议展示", () => {
  const source = readSource("components/engineering/VerificationPanel.jsx");
  assert.ok(source.includes("澄清说明（clarification）"), "缺少 clarification 展示");
  assert.ok(source.includes("clarification.code"), "读取 clarification.code");
  assert.ok(source.includes("needs_human"), "处理 needs_human 状态");
  assert.ok(source.includes("Supervisor 需要人工介入"), "缺少 needs_human 提示");
  assert.ok(source.includes("getSupervisorErrorSuggestion"), "缺少恢复建议");
  assert.ok(source.includes("needs_human/failed 运行不会伪装成功"), "缺少幂等边界说明");
});

test("Supervisor 报告入口存在且指向 reports 页", () => {
  const source = readSource("components/engineering/VerificationPanel.jsx");
  assert.ok(source.includes("报告已生成"), "缺少报告生成提示");
  assert.ok(source.includes("supervisorDetail.report_id"), "读取 report_id");
  assert.ok(source.includes("/engineering/projects/") && source.includes("/reports"), "报告入口指向 reports 页");
});

test("三句固定边界文案必须原样展示", () => {
  const source = readSource("components/engineering/VerificationPanel.jsx");
  assert.ok(source.includes("SUPERVISOR_BOUNDARY_TEXT"), "必须引用固定文案常量");
  assert.ok(source.includes("Supervisor 边界"), "组件中必须有边界提示区块");
  const utils = readSource("utils/engineeringReview.js");
  assert.ok(utils.includes("Quality Review 是确定性质量门"), "缺少质量门确定性文案");
  assert.ok(utils.includes("候选证据不会自动成为正式"), "缺少候选证据边界文案");
  assert.ok(utils.includes("质量门失败不会生成报告"), "缺少质量门失败文案");
});

test("Supervisor 不会在页面加载后自动启动", () => {
  const source = readSource("components/engineering/VerificationPanel.jsx");
  const occurrences = source.split("createSupervisorRun(").length - 1;
  assert.equal(occurrences, 1, "启动 Supervisor 只能有一个调用点（用户点击）");
  const useEffectBlocks = source.match(/useEffect\([\s\S]*?\}\s*,\s*\[[^\]]*\]\s*\)/g) || [];
  for (const block of useEffectBlocks) {
    assert.ok(!block.includes("createSupervisorRun"), "useEffect 中不得启动 Supervisor");
  }
});

test("general 区域完全不引入 Supervisor", () => {
  const workspaceDetail = readSource("pages/WorkspaceDetail.jsx");
  assert.ok(!workspaceDetail.includes("createSupervisorRun"), "general 页面不得引入 Supervisor API");
  assert.ok(!workspaceDetail.includes("supervisor_run_id"), "general 页面不得引入 Supervisor 数据");
  const appLayout = readSource("components/AppLayout.jsx");
  assert.ok(!appLayout.includes("Supervisor"), "布局不得引入 Supervisor");
});

test("Supervisor API client 位于 engineeringReviews 且不触碰 general 模块", () => {
  const client = readSource("api/engineeringReviews.js");
  assert.ok(client.includes("supervisor-runs"), "缺少 supervisor-runs 路径");
  assert.ok(client.includes("fetchSupervisorSteps"), "缺少 steps client");
  const generalClient = readSource("api/tasks.js");
  assert.ok(!generalClient.includes("supervisor"), "general API 不得包含 supervisor");
});
