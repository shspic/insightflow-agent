// 阶段 6D-2：大陆公众站法律页面、页脚与 AI 标识的静态契约测试。
// 不引入组件测试框架，直接对源码做契约断言（与 verification-workbench 同模式）。

import assert from "node:assert/strict";
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, "..");

const read = (rel) => readFileSync(path.join(SRC, rel), "utf-8");

const appSource = read("App.jsx");
const privacy = read("pages/LegalPrivacy.jsx");
const terms = read("pages/LegalTerms.jsx");
const aiDisclosure = read("pages/LegalAiDisclosure.jsx");
const footer = read("components/SiteFooter.jsx");
const siteApi = read("api/site.js");
const verificationPanel = read("components/engineering/VerificationPanel.jsx");
const reportPanel = read("components/engineering/ReviewReportPanel.jsx");
const reportCenter = read("components/ReportCenter.jsx");
const workspaceDetail = read("pages/WorkspaceDetail.jsx");
const ui = read("utils/ui.js");
const engineeringProject = read("pages/EngineeringProjectDetail.jsx");

test("三个法律页面路由已注册且公开可访问", () => {
  assert.ok(appSource.includes('path="/legal/privacy"'), "缺少 /legal/privacy 路由");
  assert.ok(appSource.includes('path="/legal/terms"'), "缺少 /legal/terms 路由");
  assert.ok(appSource.includes('path="/legal/ai-disclosure"'), "缺少 /legal/ai-disclosure 路由");
  // 公开路由：法律路由必须位于第一个 RequireSession 块之前（不经登录即可访问）
  const firstRequireSession = appSource.indexOf("<Route element={<RequireSession");
  const legalRoutes = appSource.slice(
    appSource.indexOf("<Route path=\"/legal/privacy\""),
    appSource.indexOf("<Route path=\"/legal/ai-disclosure\"") + 100,
  );
  assert.ok(firstRequireSession !== -1, "必须存在登录保护路由");
  const privacyPos = appSource.indexOf("<Route path=\"/legal/privacy\"");
  assert.ok(privacyPos < firstRequireSession, "法律页面必须在登录保护之前（公开路由）");
  assert.ok(!legalRoutes.includes("RequireSession"), "法律路由自身不得包裹登录保护");
});

test("隐私政策覆盖全部八项要求", () => {
  const requiredFragments = [
    "Excel", "CSV", "PDF", "图片",                       // 1. 上传文件类型
    "账号与登录数据", "日志数据", "模型调用数据",           // 2. 数据用途
    "数据保存期限",                                       // 3. 保存期限
    "删除方式",                                          // 4. 删除方式
    "第三方模型 API",                                     // 5. 是否发送第三方
    "无权处理", "商业秘密", "敏感数据",                    // 6. 禁止上传
    "联系我们与投诉",                                     // 7. 联系投诉
    "版本",                                              // 8. 版本
  ];
  for (const fragment of requiredFragments) {
    assert.ok(privacy.includes(fragment), `隐私政策缺少: ${fragment}`);
  }
});

test("隐私政策未知信息使用显式配置占位，不虚构", () => {
  assert.ok(privacy.includes("legal-placeholder"), "缺少占位样式类");
  assert.ok(privacy.includes("待运营者填写"), "缺少显式占位文案");
  // 不得虚构具体保存天数承诺
  assert.ok(!/保存\s*\d+\s*天/.test(privacy), "不得虚构保存期限承诺");
});

test("AI 披露页包含显式标识说明与人工复核义务", () => {
  assert.ok(aiDisclosure.includes("AI 辅助生成声明"), "缺少 AI 声明说明");
  assert.ok(aiDisclosure.includes("人工复核"), "缺少人工复核义务");
  assert.ok(aiDisclosure.includes("不承诺结果完全准确"), "不得承诺结果完全准确");
  assert.ok(aiDisclosure.includes("模型备案信息待补充"), "缺少备案办理中状态说明");
  assert.ok(aiDisclosure.includes("候选证据"), "缺少候选证据人工确认说明");
});

test("用户协议包含邀请制与使用边界", () => {
  assert.ok(terms.includes("邀请"), "用户协议缺少邀请制说明");
  assert.ok(terms.includes("不构成自动合规判断"), "缺少边界声明");
  assert.ok(terms.includes("人工复核"), "缺少人工复核要求");
});

test("页脚备案信息来源于配置", () => {
  assert.ok(footer.includes("fetchPublicSite"), "页脚必须从公开配置获取信息");
  assert.ok(footer.includes("icp_filing_number"), "页脚必须使用 ICP 配置字段");
  assert.ok(footer.includes("public_security_filing_number"), "页脚必须使用公安备案配置字段");
  assert.ok(footer.includes("site_operator_name"), "页脚必须使用运营主体配置字段");
  assert.ok(footer.includes("site_contact_email"), "页脚必须使用联系邮箱配置字段");
  assert.ok(footer.includes("beian.miit.gov.cn") || footer.includes("icp_filing_url"),
    "ICP 链接必须来自配置");
});

test("备案号为空时不显示伪造号码", () => {
  assert.ok(footer.includes("hasIcp"), "缺少 ICP 号存在性判断");
  assert.ok(footer.includes("hasSecurity"), "缺少公安备案号存在性判断");
  assert.ok(footer.includes("待补充"), "ICP 号为空时应显示待补充");
  assert.ok(footer.includes("公安联网备案办理中"), "公安备案未完成时应显示办理中状态");
  // 不得硬编码任何真实备案号
  assert.ok(!/ICP备\d+号/.test(footer), "页脚不得硬编码备案号");
  assert.ok(!/公网安备\d+号/.test(footer), "页脚不得硬编码公安备案号");
});

test("智能核验页与报告页包含 AI 辅助生成提示", () => {
  assert.ok(verificationPanel.includes("ai_assisted_notice"), "智能核验页必须读取 AI 提示配置");
  assert.ok(verificationPanel.includes("AI 辅助生成，须人工复核") || verificationPanel.includes("aiNotice"),
    "智能核验页缺少 AI 提示");
  assert.ok(verificationPanel.includes("候选证据只有人工接受后才成为正式 Evidence"),
    "智能核验页缺少候选证据人工确认说明");
  assert.ok(reportPanel.includes("ai_assisted_notice"), "报告页必须读取 AI 提示配置");
  assert.ok(reportPanel.includes("不承诺结果完全准确"), "报告页声明不得承诺完全准确");
  assert.ok(reportCenter.includes("ai_assisted_notice"), "报告中心必须读取 AI 提示配置");
  assert.ok(reportCenter.includes("不承诺结果完全准确"), "报告中心声明不得承诺完全准确");
});

test("general 页面不误引入 engineering 内部数据", () => {
  assert.ok(!workspaceDetail.includes("智能核验"), "general 页面不得出现智能核验");
  assert.ok(!workspaceDetail.includes("VerificationPanel"), "general 页面不得引入 VerificationPanel");
  assert.ok(!workspaceDetail.includes("Supervisor"), "general 页面不得出现 Supervisor");
});

test("页面标题覆盖法律路由", () => {
  assert.ok(ui.includes('"/legal/privacy"'), "缺少隐私政策标题");
  assert.ok(ui.includes('"/legal/terms"'), "缺少用户协议标题");
  assert.ok(ui.includes('"/legal/ai-disclosure"'), "缺少 AI 披露标题");
});

test("公开配置 API 客户端不引用任何密钥", () => {
  assert.ok(siteApi.includes("api/public/site"), "客户端必须指向公开端点");
  for (const forbidden of ["DEEPSEEK_API_KEY", "ENGINEERING_MCP_INTERNAL_TOKEN",
    "AUTH_SECRET_KEY", "Authorization"]) {
    assert.ok(!siteApi.includes(forbidden), `site.js 不得引用 ${forbidden}`);
  }
});

test("前端源码不引用任何后端密钥环境变量", () => {
  // 递归扫描 src 下的 js/jsx，确认没有任何真实密钥环境变量引用
  let result;
  try {
    result = execSync(
      `grep -rn "DEEPSEEK_API_KEY\\|ENGINEERING_MCP_INTERNAL_TOKEN\\|AUTH_SECRET_KEY" ${SRC} --include="*.js" --include="*.jsx" --exclude="*.test.js" || true`,
      { encoding: "utf-8" },
    );
  } catch (error) {
    result = error.stdout || "";
  }
  assert.equal(result.trim(), "", `前端源码不得引用后端密钥: ${result.trim()}`);
});

test("法律页面与页脚样式存在（390px 防溢出基础）", () => {
  const css = read("App.css");
  assert.ok(css.includes(".site-footer"), "缺少页脚样式");
  assert.ok(css.includes(".legal-document"), "缺少法律文档样式");
  assert.ok(css.includes("overflow-wrap: anywhere"), "法律文档必须允许长文本换行");
  assert.ok(css.includes("@media (max-width: 480px)"), "缺少移动端断点样式");
});
