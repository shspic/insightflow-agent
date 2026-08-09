import { expect, test } from "@playwright/test";

const primaryUser = process.env.STAGE6B_USERNAME;
const primaryPassword = process.env.STAGE6B_PASSWORD;
const secondaryUser = process.env.STAGE6B_SECONDARY_USERNAME;
const secondaryPassword = process.env.STAGE6B_SECONDARY_PASSWORD;
const projectId = process.env.STAGE6B_PROJECT_ID;

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

test("黄金项目关键结果可在真实浏览器中复核", async ({ page }) => {
  requireEnvironment({ STAGE6B_USERNAME: primaryUser, STAGE6B_PASSWORD: primaryPassword, STAGE6B_PROJECT_ID: projectId });
  await login(page, primaryUser, primaryPassword);

  await page.goto(`/engineering/projects/${projectId}/verification`);
  await expect(page.getByRole("heading", { name: "智能核验" }).first()).toBeVisible();
  await expect(page.getByText("Supervisor 详情", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("已接受为正式证据", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("已拒绝", { exact: true }).first()).toBeVisible();

  await page.goto(`/engineering/projects/${projectId}/findings`);
  await expect(page.locator(".finding-card").filter({ hasText: "已确认" }).first()).toBeVisible();
  await expect(page.locator(".finding-card").filter({ hasText: "已驳回" }).first()).toBeVisible();
  await expect(page.locator(".finding-card").filter({ hasText: "已修改" }).first()).toBeVisible();

  await page.goto(`/engineering/projects/${projectId}/reports`);
  await expect(page.getByText("v1", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("v2", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("v3", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "下载 Markdown" })).toBeVisible();
  await expect(page.getByRole("button", { name: "下载 PDF" })).toBeVisible();
});

test("智能核验页在 390px 移动视口没有整页横向溢出", async ({ page }) => {
  requireEnvironment({ STAGE6B_USERNAME: primaryUser, STAGE6B_PASSWORD: primaryPassword, STAGE6B_PROJECT_ID: projectId });
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, primaryUser, primaryPassword);
  await page.goto(`/engineering/projects/${projectId}/verification`);
  await expect(page.getByRole("heading", { name: "智能核验" }).first()).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBe(dimensions.clientWidth);
});

test("第二用户无法读取第一用户的工程项目", async ({ page }) => {
  requireEnvironment({
    STAGE6B_SECONDARY_USERNAME: secondaryUser,
    STAGE6B_SECONDARY_PASSWORD: secondaryPassword,
    STAGE6B_PROJECT_ID: projectId,
  });
  await login(page, secondaryUser, secondaryPassword);
  await page.goto(`/engineering/projects/${projectId}`);
  await expect(page.getByText("工程项目无法加载")).toBeVisible();
  await expect(page.getByText("工作区不存在")).toBeVisible();
});
