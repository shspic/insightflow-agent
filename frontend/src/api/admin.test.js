import assert from "node:assert/strict";
import test from "node:test";

import { buildInviteCodePayload } from "./admin.js";

test("自定义邀请码表单会去除首尾空白并保留最大使用次数", () => {
  assert.deepEqual(buildInviteCodePayload("  Custom_Code-2026  ", "3"), {
    code: "Custom_Code-2026",
    max_uses: 3,
  });
});

test("自定义邀请码留空时不发送 code，由后端保持随机生成", () => {
  assert.deepEqual(buildInviteCodePayload("   ", "5"), {
    max_uses: 5,
  });
});
