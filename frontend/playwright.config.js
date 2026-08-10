import { defineConfig, devices } from "@playwright/test";

// 本机（Stage 6B 验证）默认使用系统 Chrome；
// CI 无系统浏览器时设置 PW_CHROMIUM_CHANNEL=none，使用 Playwright 自带 Chromium。
const channel = process.env.PW_CHROMIUM_CHANNEL === "none"
  ? undefined
  : (process.env.PW_CHROMIUM_CHANNEL || "chrome");

const baseURL = process.env.STAGE6B_BASE_URL || process.env.CI_SMOKE_BASE_URL || "http://127.0.0.1:5173";

// 输出目录可覆盖：CI 冒烟使用独立目录，不污染 Stage 6B 产物。
const outputDir = process.env.PW_OUTPUT_DIR || "../output/playwright/stage6b-test-results";

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  outputDir,
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      // 本机/6B：系统 Chrome
      name: "chromium",
      use: { ...devices["Desktop Chrome"], channel },
    },
    {
      // CI 冒烟：无系统 Chrome 时使用 Playwright 自带 Chromium
      name: "chromium-ci",
      use: { ...devices["Desktop Chrome"], channel },
    },
  ],
});
