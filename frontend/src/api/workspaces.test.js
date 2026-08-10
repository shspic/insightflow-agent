import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const workspacesApi = read("../api/workspaces.js");

test("deleteWorkspace 使用 DELETE method 和正确 URL 模式", () => {
  // URL 模式: /workspaces/${workspaceId}
  assert.match(workspacesApi, /\$\{.*workspaceId\}/);
  assert.match(workspacesApi, /method:\s*"DELETE"/);
});

test("deleteWorkspace 请求体包含 confirmation_name", () => {
  assert.match(workspacesApi, /confirmation_name/);
  // 发送 JSON body
  assert.match(workspacesApi, /JSON\.stringify/);
});

test("workspaces API 不导出 restoreWorkspace", () => {
  // 不应有 export.*restoreWorkspace
  assert.doesNotMatch(workspacesApi, /restoreWorkspace/);
});

test("createWorkspace 和 updateWorkspace 仍通过 POST/PATCH 正常工作", () => {
  assert.match(workspacesApi, /method:\s*"POST"/);
  assert.match(workspacesApi, /method:\s*"PATCH"/);
});
