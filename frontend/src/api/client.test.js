import assert from "node:assert/strict";
import test from "node:test";

import { login, register, submitPasswordReset } from "./auth.js";
import { resetCsrfToken } from "./client.js";

function jsonResponse(status, data) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  };
}

test.beforeEach(() => {
  resetCsrfToken();
  globalThis.document = { cookie: "insightflow_csrf=stale-browser-cookie" };
  globalThis.window = { dispatchEvent() {} };
  globalThis.CustomEvent = class {
    constructor(type) {
      this.type = type;
    }
  };
});

test.afterEach(() => {
  resetCsrfToken();
  delete globalThis.fetch;
  delete globalThis.document;
  delete globalThis.window;
  delete globalThis.CustomEvent;
});

test("注册前从服务端获取新 CSRF，且不盲信旧 Cookie", async () => {
  const requests = [];
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url, options });
    if (url.endsWith("/auth/csrf")) {
      return jsonResponse(200, { csrf_token: "fresh-token" });
    }
    assert.equal(options.headers.get("X-CSRF-Token"), "fresh-token");
    assert.equal(options.credentials, "include");
    return jsonResponse(201, { username: "new.user" });
  };

  const result = await register({
    username: "new.user",
    password: "SafePassword!2026",
    password_confirm: "SafePassword!2026",
    invite_code: "Custom_Code-2026",
  });

  assert.equal(result.username, "new.user");
  assert.deepEqual(requests.map((item) => item.url), [
    "/api/v2/auth/csrf",
    "/api/v2/auth/register",
  ]);
});

test("密码重置申请复用统一的公共 CSRF 请求流程", async () => {
  const requests = [];
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url, options });
    if (url.endsWith("/auth/csrf")) {
      return jsonResponse(200, { csrf_token: "reset-token" });
    }
    assert.equal(options.headers.get("X-CSRF-Token"), "reset-token");
    assert.equal(options.credentials, "include");
    return jsonResponse(200, { message: "申请已提交" });
  };

  const result = await submitPasswordReset({ username: "reset.user" });

  assert.equal(result.message, "申请已提交");
  assert.deepEqual(requests.map((item) => item.url), [
    "/api/v2/auth/csrf",
    "/api/v2/auth/password-reset-requests",
  ]);
});

test("后端密钥变化后，注册遇到明确 CSRF 403 时仅刷新并重试一次", async () => {
  const requests = [];
  let csrfIssue = 0;
  let registerAttempt = 0;
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url, token: options.headers?.get?.("X-CSRF-Token") });
    if (url.endsWith("/auth/csrf")) {
      csrfIssue += 1;
      return jsonResponse(200, {
        csrf_token: csrfIssue === 1 ? "old-public-token" : "new-public-token",
      });
    }
    if (url.endsWith("/auth/login")) {
      return jsonResponse(200, {
        user: { username: "old.admin" },
        csrf_token: "old-session-token",
      });
    }
    registerAttempt += 1;
    if (registerAttempt === 1) {
      return jsonResponse(403, {
        detail: { code: "CSRF_VALIDATION_FAILED", message: "CSRF 校验失败" },
      });
    }
    assert.equal(options.headers.get("X-CSRF-Token"), "new-public-token");
    return jsonResponse(201, { username: "recovered.user" });
  };

  await login({ username: "old.admin", password: "SafePassword!2026" });
  const result = await register({
    username: "recovered.user",
    password: "SafePassword!2026",
    password_confirm: "SafePassword!2026",
    invite_code: "Custom_Code-2026",
  });

  assert.equal(result.username, "recovered.user");
  assert.equal(registerAttempt, 2);
  assert.deepEqual(requests.slice(2).map((item) => [item.url, item.token]), [
    ["/api/v2/auth/register", "old-session-token"],
    ["/api/v2/auth/csrf", undefined],
    ["/api/v2/auth/register", "new-public-token"],
  ]);
});

test("邀请码业务错误不会触发 CSRF 刷新或重复注册", async () => {
  let csrfIssue = 0;
  let registerAttempt = 0;
  globalThis.fetch = async (url) => {
    if (url.endsWith("/auth/csrf")) {
      csrfIssue += 1;
      return jsonResponse(200, { csrf_token: "valid-token" });
    }
    registerAttempt += 1;
    return jsonResponse(400, { detail: "邀请码无效或不可用" });
  };

  await assert.rejects(
    register({
      username: "invalid.invite",
      password: "SafePassword!2026",
      password_confirm: "SafePassword!2026",
      invite_code: "Wrong_Code-2026",
    }),
    /邀请码无效或不可用/,
  );
  assert.equal(csrfIssue, 1);
  assert.equal(registerAttempt, 1);
});

test("连续两次明确 CSRF 403 后停止，不会无限重试", async () => {
  let csrfIssue = 0;
  let registerAttempt = 0;
  globalThis.fetch = async (url) => {
    if (url.endsWith("/auth/csrf")) {
      csrfIssue += 1;
      return jsonResponse(200, { csrf_token: `token-${csrfIssue}` });
    }
    registerAttempt += 1;
    return jsonResponse(403, {
      detail: { code: "CSRF_VALIDATION_FAILED", message: "CSRF 校验失败" },
    });
  };

  await assert.rejects(
    register({
      username: "csrf.failure",
      password: "SafePassword!2026",
      password_confirm: "SafePassword!2026",
      invite_code: "Custom_Code-2026",
    }),
    (error) => error.status === 403 && error.code === "CSRF_VALIDATION_FAILED",
  );
  assert.equal(csrfIssue, 2);
  assert.equal(registerAttempt, 2);
});
