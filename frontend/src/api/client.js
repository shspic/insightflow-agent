import { API_BASE_URL, V2_API_BASE_URL } from "./config.js";

const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const CSRF_ERROR_CODE = "CSRF_VALIDATION_FAILED";
let csrfToken = null;
let csrfRequest = null;

export class ApiError extends Error {
  constructor(message, status, code = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function clearCsrfToken() {
  csrfToken = null;
}

async function ensureCsrfToken({ forceRefresh = false } = {}) {
  if (!forceRefresh && csrfToken) {
    return csrfToken;
  }
  if (csrfRequest) {
    return csrfRequest;
  }
  clearCsrfToken();
  csrfRequest = (async () => {
    const response = await fetch(`${V2_API_BASE_URL}/auth/csrf`, {
      credentials: "include",
    });
    if (!response.ok) {
      throw new ApiError("无法建立安全请求上下文", response.status);
    }
    const data = await response.json().catch(() => null);
    if (!data?.csrf_token) {
      throw new ApiError("未收到 CSRF Token，请确认使用同源访问或 Vite Proxy", 403);
    }
    csrfToken = data.csrf_token;
    return csrfToken;
  })();
  try {
    return await csrfRequest;
  } finally {
    csrfRequest = null;
  }
}

function getErrorMessage(data, status) {
  const detail = data?.detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (detail?.message) {
    return detail.message;
  }
  const defaults = {
    401: "登录状态已失效，请重新登录",
    403: "没有权限执行此操作",
    404: "请求的资源不存在",
    409: "当前状态不允许此操作",
    413: "文件过大或单次文件数量超过限制",
    415: "文件类型、MIME 或内容特征不受支持",
    422: "文件内容或提交格式未通过服务端校验",
    429: "配额不足或操作过于频繁，请稍后重试",
    500: "服务器暂时无法处理请求",
  };
  return defaults[status] || "请求失败，请稍后重试";
}

export async function apiRequest(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const needsCsrf = MUTATING_METHODS.has(method);

  for (let attempt = 0; attempt < 2; attempt += 1) {
    const headers = new Headers(options.headers || {});
    if (needsCsrf) {
      headers.set("X-CSRF-Token", await ensureCsrfToken({ forceRefresh: attempt === 1 }));
    }
    if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(`${V2_API_BASE_URL}${path}`, {
      ...options,
      method,
      headers,
      credentials: "include",
    });
    const data = await response.json().catch(() => null);
    if (data?.csrf_token) {
      csrfToken = data.csrf_token;
    }
    if (response.ok) {
      if (path === "/auth/logout" || path === "/auth/revoke-sessions") {
        clearCsrfToken();
      }
      return data;
    }

    const code = typeof data?.detail === "object"
      ? (data.detail.code || data.detail.error_code || null)
      : null;
    if (
      needsCsrf
      && response.status === 403
      && code === CSRF_ERROR_CODE
      && attempt === 0
    ) {
      clearCsrfToken();
      continue;
    }

    const error = new ApiError(getErrorMessage(data, response.status), response.status, code);
    if (response.status === 401) {
      clearCsrfToken();
      window.dispatchEvent(new CustomEvent("auth:unauthorized"));
    }
    if (code === "PASSWORD_CHANGE_REQUIRED") {
      window.dispatchEvent(new CustomEvent("auth:password-change-required"));
    }
    if (import.meta.env?.DEV && response.status !== 401) {
      console.error("API 请求失败", { path, status: response.status, data });
    }
    throw error;
  }
  throw new ApiError("CSRF 校验失败", 403, CSRF_ERROR_CODE);
}

export function resetCsrfToken() {
  clearCsrfToken();
  csrfRequest = null;
}

export function apiResourceUrl(path) {
  return `${API_BASE_URL}${path}`;
}

export async function downloadResource(path, fallbackName = "download") {
  const response = await fetch(apiResourceUrl(path), { credentials: "include" });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new ApiError(
      getErrorMessage(data, response.status),
      response.status,
      data?.detail?.code || data?.detail?.error_code || null,
    );
  }
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") || "";
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
  const plain = /filename="?([^";]+)"?/i.exec(disposition)?.[1];
  const filename = encoded ? decodeURIComponent(encoded) : plain || fallbackName;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
