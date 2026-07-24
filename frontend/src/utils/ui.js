export const TASK_STATUS = {
  draft: ["草稿", "neutral"],
  awaiting_clarification: ["等待补充信息", "warning"],
  planning: ["生成计划中", "info"],
  awaiting_confirmation: ["等待确认", "warning"],
  queued: ["排队中", "info"],
  running: ["执行中", "info"],
  reviewing: ["质量审核中", "info"],
  retrying: ["重试中", "warning"],
  completed: ["已完成", "success"],
  completed_with_warnings: ["已完成，有警告", "warning"],
  failed: ["失败", "danger"],
  cancelled: ["已取消", "neutral"],
};

export const FILE_STATUS = {
  pending: ["等待处理", "neutral"],
  uploaded: ["已上传", "info"],
  validating: ["校验中", "info"],
  parsing: ["解析中", "info"],
  profiling: ["理解中", "info"],
  ready: ["已就绪", "success"],
  failed: ["失败", "danger"],
  unsupported: ["不支持", "warning"],
};

export const RELATION_STATUS = {
  suggested: ["待确认", "warning"],
  confirmed: ["已确认", "success"],
  rejected: ["已拒绝", "neutral"],
  superseded: ["已替代", "neutral"],
};

export const AGENT_LABELS = {
  supervisor: "主管 Agent",
  file_understanding_agent: "文件理解 Agent",
  data_analysis_agent: "数据分析 Agent",
  document_research_agent: "文档检索 Agent",
  report_agent: "报告生成 Agent",
  quality_review_agent: "质量审核 Agent",
};

export function statusMeta(status, dictionary = TASK_STATUS) {
  const [label, tone] = dictionary[status] || [status || "未知", "neutral"];
  return { label, tone };
}

export function quotaState(usage, limit) {
  if (usage === null || usage === undefined || !Number.isFinite(Number(limit)) || Number(limit) <= 0) {
    return { ratio: 0, percent: 0, tone: "neutral", warning: false };
  }
  const ratio = Math.max(0, Number(usage) / Number(limit));
  return {
    ratio,
    percent: Math.min(100, Math.round(ratio * 100)),
    tone: ratio >= 1 ? "danger" : ratio >= 0.8 ? "warning" : "success",
    warning: ratio >= 0.8,
  };
}

export function mergeEvents(current = [], additions = [], limit = 300) {
  const byId = new Map();
  [...current, ...additions].forEach((event) => {
    if (event?.id !== undefined && event?.id !== null) byId.set(event.id, event);
  });
  return [...byId.values()]
    .sort((left, right) => Number(left.id) - Number(right.id))
    .slice(-limit);
}

export function sortReportVersions(reports = []) {
  return [...reports].sort((left, right) => {
    if (left.is_current !== right.is_current) return left.is_current ? -1 : 1;
    return Number(right.version || 0) - Number(left.version || 0);
  });
}

export function validatePlanSteps(steps = []) {
  if (!steps.length) return { valid: false, message: "计划至少需要一个步骤" };
  const keys = new Set(steps.map((step) => step.step_key));
  if (keys.size !== steps.length) return { valid: false, message: "计划步骤标识不能重复" };
  for (const [index, step] of steps.entries()) {
    const prior = new Set(steps.slice(0, index).map((item) => item.step_key));
    if ((step.depends_on || []).some((key) => !keys.has(key) || !prior.has(key))) {
      return { valid: false, message: `第 ${index + 1} 步存在无效或倒序依赖` };
    }
  }
  const review = steps.at(-1);
  if (review?.agent_type !== "quality_review_agent") {
    return { valid: false, message: "质量审核必须是最后一步" };
  }
  return { valid: true, message: "" };
}

export function fileTypeMeta(fileType = "") {
  const normalized = fileType.toLowerCase().replace(/^\./, "");
  const map = {
    csv: ["CSV", "表"],
    xlsx: ["Excel", "表"],
    pdf: ["PDF", "文"],
    png: ["PNG", "图"],
    jpg: ["JPG", "图"],
    jpeg: ["JPEG", "图"],
    webp: ["WEBP", "图"],
    md: ["Markdown", "文"],
    markdown: ["Markdown", "文"],
  };
  const [label, glyph] = map[normalized] || [normalized.toUpperCase() || "文件", "件"];
  return { label, glyph };
}

export function allowedNavigation(role) {
  const items = ["workspaces", "usage"];
  if (role === "admin") items.push("admin");
  return items;
}

export function normalizeTheme(value) {
  return ["light", "dark", "system"].includes(value) ? value : "system";
}

export function readThemePreference(storage, key = "insightflow-theme") {
  try {
    return normalizeTheme(storage?.getItem(key));
  } catch {
    return "system";
  }
}

export function oneTimeSecretReducer(state, action) {
  if (action.type === "show") return { title: action.title, value: action.value, visible: true };
  if (action.type === "clear") return { title: "", value: "", visible: false };
  return state;
}

export function formatBytes(value) {
  const number = Number(value || 0);
  if (number < 1024) return `${number} B`;
  if (number < 1024 ** 2) return `${(number / 1024).toFixed(1)} KB`;
  if (number < 1024 ** 3) return `${(number / 1024 ** 2).toFixed(1)} MB`;
  return `${(number / 1024 ** 3).toFixed(1)} GB`;
}

export function formatDate(value, fallback = "—") {
  if (!value) return fallback;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? fallback : date.toLocaleString("zh-CN");
}

export function mapApiError(error) {
  const byStatus = {
    400: ["请求无法处理", "请检查输入内容后重试。"],
    401: ["登录状态已失效", "请重新登录，未提交的本地表单不会被上传。"],
    403: ["没有操作权限", "返回上一页或联系管理员确认权限。"],
    404: ["资源不存在", "它可能已被删除、归档或不属于当前工作区。"],
    409: ["当前状态不允许操作", "刷新状态后再重试。"],
    413: ["文件或批量数量超限", "减少文件数量或选择更小的文件。"],
    415: ["文件类型不受支持", "请使用页面列出的格式重新上传。"],
    422: ["内容未通过校验", "检查文件内容或表单字段后重试。"],
    429: ["配额不足或操作过于频繁", "前往使用量页面查看上限与重置时间。"],
    500: ["服务暂时不可用", "稍后重试；若持续发生，请复制错误标识给管理员。"],
  };
  const [title, action] = byStatus[error?.status] || ["网络请求失败", "检查网络连接后重试。"];
  return {
    title,
    message: error?.message || "请求未完成。",
    action,
    technicalId: error?.code || (error?.status ? `HTTP_${error.status}` : "NETWORK_ERROR"),
  };
}
