import { expect, test } from "@playwright/test";

/**
 * Stage 6C CI 浏览器冒烟（独立、可重复）：
 * - 数据由 scripts/ci_smoke_setup.py 在隔离临时数据库/存储中自动生成，
 *   不依赖本机 app.db，不依赖 Stage 6B 已准备好的本地项目；
 * - 覆盖：登录、engineering 页面、关键核验页面、跨用户隔离、390px 移动端；
 * - 环境变量：CI_SMOKE_BASE_URL / CI_SMOKE_WORKSPACE_ID /
 *   CI_SMOKE_PRIMARY_USER / CI_SMOKE_PRIMARY_PASSWORD /
 *   CI_SMOKE_SECONDARY_USER / CI_SMOKE_SECONDARY_PASSWORD。
 */

const baseURL = process.env.CI_SMOKE_BASE_URL || "http://127.0.0.1:5173";
const workspaceId = process.env.CI_SMOKE_WORKSPACE_ID;
const primaryUser = process.env.CI_SMOKE_PRIMARY_USER;
const primaryPassword = process.env.CI_SMOKE_PRIMARY_PASSWORD;
const secondaryUser = process.env.CI_SMOKE_SECONDARY_USER;
const secondaryPassword = process.env.CI_SMOKE_SECONDARY_PASSWORD;

function requireEnvironment(values) {
  for (const [name, value] of Object.entries(values)) {
    expect(value, `缺少环境变量 ${name}`).toBeTruthy();
  }
}

async function login(page, username, password) {
  await page.goto("/login");
  await page.getByRole("textbox", { name: "账号" }).fill(username);
  await page.getByRole("textbox", { name: /密码/ }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/(general|engineering)/);
}

test("主用户登录后进入 engineering 项目列表", async ({ page }) => {
  requireEnvironment({ CI_SMOKE_PRIMARY_USER: primaryUser, CI_SMOKE_PRIMARY_PASSWORD: primaryPassword });
  await login(page, primaryUser, primaryPassword);
  await page.goto("/engineering/projects");
  // 工程投标审查入口可见（页面级文本，不依赖具体数据）
  await expect(page.getByText("工程投标审查").first()).toBeVisible();
  // 冒烟项目卡片可见（setup 脚本生成的数据）
  await expect(page.getByText("CI 冒烟审查项目").first()).toBeVisible();
});

test("主用户可打开审查项目并进入关键核验页面", async ({ page }) => {
  requireEnvironment({
    CI_SMOKE_PRIMARY_USER: primaryUser,
    CI_SMOKE_PRIMARY_PASSWORD: primaryPassword,
    CI_SMOKE_WORKSPACE_ID: workspaceId,
  });
  await login(page, primaryUser, primaryPassword);
  await page.goto(`/engineering/projects/${workspaceId}`);
  // 项目详情加载：材料/核验/报告导航可见
  await expect(page.getByText("CI 冒烟审查项目").first()).toBeVisible();
  await page.goto(`/engineering/projects/${workspaceId}/verification`);
  // 关键核验页面：智能核验标题可见（确定性 pipeline 数据已生成）
  await expect(page.getByRole("heading", { name: "智能核验" }).first()).toBeVisible();
});

test("第二用户无法读取第一用户的审查项目（跨用户隔离）", async ({ page }) => {
  requireEnvironment({
    CI_SMOKE_SECONDARY_USER: secondaryUser,
    CI_SMOKE_SECONDARY_PASSWORD: secondaryPassword,
    CI_SMOKE_WORKSPACE_ID: workspaceId,
  });
  await login(page, secondaryUser, secondaryPassword);
  await page.goto(`/engineering/projects/${workspaceId}`);
  await expect(page.getByText("工程项目无法加载")).toBeVisible();
  await expect(page.getByText("工作区不存在").first()).toBeVisible();
});

test("核验页在 390px 移动视口没有整页横向溢出", async ({ page }) => {
  requireEnvironment({
    CI_SMOKE_PRIMARY_USER: primaryUser,
    CI_SMOKE_PRIMARY_PASSWORD: primaryPassword,
    CI_SMOKE_WORKSPACE_ID: workspaceId,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, primaryUser, primaryPassword);
  await page.goto(`/engineering/projects/${workspaceId}/verification`);
  await expect(page.getByRole("heading", { name: "智能核验" }).first()).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBe(dimensions.clientWidth);
});
