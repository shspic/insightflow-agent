import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const tokens = read("../styles/tokens.css");
const styles = read("../App.css");
const common = read("../components/common/index.jsx");
const uploader = read("../components/BatchFileUploader.jsx");
const workspaceList = read("../pages/WorkspaceList.jsx");
const reportCenter = read("../components/ReportCenter.jsx");
const login = read("../pages/Login.jsx");
const authContext = read("../context/AuthContext.jsx");
const indexHtml = read("../../index.html");

test("浅蓝语义 Token 覆盖页面、表面、文字、边框和状态", () => {
  [
    "--color-page-background: #f3f7fc",
    "--color-surface-primary: #ffffff",
    "--color-text-primary: #10243e",
    "--color-border-default: #d7e4f0",
    "--color-primary: #1677ff",
    "--color-accent-cyan: #12a9c2",
    "--color-success-soft: #eaf8ef",
    "--color-danger-soft: #fff0f1",
  ].forEach((token) => assert.match(tokens, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));
});

test("Button 支持完整语义、loading 防重复提交并保留原标签宽度", () => {
  assert.match(styles, /\.ui-button--success/);
  assert.match(styles, /\.ui-button--link/);
  assert.match(styles, /\.ui-button--danger/);
  assert.match(common, /disabled=\{disabled \|\| loading\}/);
  assert.match(common, /ui-button__label is-loading/);
  assert.match(common, /aria-busy=\{loading \|\| undefined\}/);
});

test("破坏性操作使用 danger，普通取消按钮仍为 secondary", () => {
  assert.match(workspaceList, /<Button variant="danger"[\s\S]{0,120}软删除<\/Button>/);
  assert.match(reportCenter, /<Button size="sm" variant="danger"[\s\S]{0,120}删除版本<\/Button>/);
  assert.match(workspaceList, /<Button variant="secondary"[\s\S]{0,120}>取消<\/Button>/);
});

test("上传使用真实不确定状态，不显示固定虚假百分比", () => {
  assert.doesNotMatch(uploader, /value=\{?45\}?/);
  assert.match(uploader, /role="status"/);
  assert.match(uploader, /不显示估算百分比/);
});

test("表单错误、空状态、Dialog 和 reduced motion 具备可访问性契约", () => {
  assert.match(common, /aria-describedby/);
  assert.match(common, /role="alert"/);
  assert.match(common, /aria-modal="true"/);
  assert.match(common, /role="status"/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
});

test("浏览器品牌资源和移动端无整页溢出约束存在", () => {
  assert.match(indexHtml, /href="\/favicon\.png"/);
  assert.match(indexHtml, /InsightFlow Agent/);
  assert.match(styles, /overflow-x: clip/);
  assert.match(styles, /@media \(max-width: 640px\)/);
  assert.match(styles, /\.topbar \.mobile-menu/);
});

test("登录表单具备错误、loading 与失败后结束状态", () => {
  assert.match(login, /<Alert title="登录未成功" tone="danger">/);
  assert.match(login, /loading=\{isSubmitting\}/);
  assert.match(login, /finally\s*\{\s*setIsSubmitting\(false\)/);
  assert.match(login, /autoComplete="username"/);
  assert.match(login, /autoComplete="current-password"/);
});

test("登录成功后必须再次通过 me 接口确认 Cookie Session", () => {
  assert.match(authContext, /await authApi\.login\(payload\)/);
  assert.match(authContext, /await authApi\.fetchCurrentUser\(\)/);
});
