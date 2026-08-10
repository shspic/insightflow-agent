// 阶段 6D-2：大陆公众站法律页面 Playwright 验证（公开路由，无需登录）。
// - 三个法律页面在桌面与 390px 移动视口可访问且无整页横向溢出
// - 页脚存在且不含伪造备案号
// 依赖后端提供 /api/public/site；无后端时页面显示模板占位（仍可访问）。

import { expect, test } from "@playwright/test";

const LEGAL_PAGES = [
  { path: "/legal/privacy", heading: "隐私政策" },
  { path: "/legal/terms", heading: "用户协议" },
  { path: "/legal/ai-disclosure", heading: "AI 辅助功能说明" },
];

async function assertNoHorizontalOverflow(page) {
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBe(dimensions.clientWidth);
}

for (const { path, heading } of LEGAL_PAGES) {
  test(`桌面：${heading}页面可访问且无横向溢出`, async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading }).first()).toBeVisible();
    await assertNoHorizontalOverflow(page);
  });

  test(`390px：${heading}页面无整页横向溢出`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading }).first()).toBeVisible();
    await assertNoHorizontalOverflow(page);
  });
}

test("登录页包含全站页脚与法律入口", async ({ page }) => {
  await page.goto("/login");
  await expect(page.locator("footer.site-footer")).toBeVisible();
  await expect(page.getByRole("link", { name: "隐私政策" })).toBeVisible();
  await expect(page.getByRole("link", { name: "用户协议" })).toBeVisible();
  await expect(page.getByRole("link", { name: "AI 辅助功能说明" })).toBeVisible();
  // 公安备案号为空时必须显示"办理中"状态，不得伪造号码
  const footerText = await page.locator("footer.site-footer").innerText();
  expect(footerText).toContain("公安联网备案办理中");
  expect(footerText).not.toMatch(/[一-龥]{1,2}公网安备\d+号/);
});

test("登录页 390px 无整页横向溢出", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/login");
  await assertNoHorizontalOverflow(page);
});
