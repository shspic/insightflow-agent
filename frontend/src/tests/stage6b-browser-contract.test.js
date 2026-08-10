import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

function readSource(relativePath) {
  return readFileSync(join(SRC, relativePath), "utf-8");
}

test("Supervisor 详情请求已显式导入且用于加载四节点轨迹", () => {
  const source = readSource("components/engineering/VerificationPanel.jsx");
  const importEnd = source.indexOf("} from \"../../api/engineeringReviews\";");
  assert.ok(importEnd > 0, "未找到 engineeringReviews 导入块");
  assert.ok(source.slice(0, importEnd).includes("fetchSupervisorRun,"));
  assert.ok(source.includes("fetchSupervisorRun(workspaceId, effectiveRunId, supervisorRunId)"));
});

test("current ReviewBrief 的预期 404 仅抑制开发日志且控制字段不进入 fetch", () => {
  const client = readSource("api/client.js");
  const reviews = readSource("api/engineeringReviews.js");
  assert.ok(client.includes("const { suppressDevError = false, ...requestOptions } = options;"));
  assert.ok(client.includes("...requestOptions,"));
  assert.ok(client.includes("!suppressDevError"));
  assert.ok(reviews.includes("suppressDevError: true"));
});

test("智能核验的直接子项允许在移动视口内收缩", () => {
  const css = readSource("App.css");
  assert.ok(css.includes(".engineering-stack > *"));
  assert.match(css, /\.engineering-stack > \*\s*\{[^}]*min-width:\s*0;/s);
  assert.match(css, /\.engineering-stack > \*\s*\{[^}]*max-width:\s*100%;/s);
});
