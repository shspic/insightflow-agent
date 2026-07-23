import { apiRequest, apiResourceUrl } from "./client";

const base = (workspaceId) => `/workspaces/${workspaceId}/tasks`;

export const fetchWorkspaceTasks = (workspaceId) => apiRequest(base(workspaceId));
export const createWorkspaceTask = (workspaceId, payload) =>
  apiRequest(base(workspaceId), { method: "POST", body: JSON.stringify(payload) });
export const fetchWorkspaceTaskTrace = (workspaceId, taskId) =>
  apiRequest(`${base(workspaceId)}/${taskId}/trace`);
export const fetchWorkspaceReport = (workspaceId, taskId) =>
  apiRequest(`${base(workspaceId)}/${taskId}/report`);
export const generateWorkspaceReport = (workspaceId, taskId) =>
  apiRequest(`${base(workspaceId)}/${taskId}/report`, { method: "POST" });

export const createWorkspaceTaskDraft = (workspaceId, payload) =>
  apiRequest(`${base(workspaceId)}/drafts`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const fetchWorkspaceTask = (workspaceId, taskId) =>
  apiRequest(`${base(workspaceId)}/${taskId}`);
export const answerTaskClarification = (workspaceId, taskId, payload) =>
  apiRequest(`${base(workspaceId)}/${taskId}/clarifications`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const regenerateTaskPlan = (workspaceId, taskId) =>
  apiRequest(`${base(workspaceId)}/${taskId}/plans/regenerate`, { method: "POST" });
export const patchTaskPlan = (workspaceId, taskId, planId, payload) =>
  apiRequest(`${base(workspaceId)}/${taskId}/plans/${planId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
export const confirmTaskPlan = (workspaceId, taskId, planId) =>
  apiRequest(`${base(workspaceId)}/${taskId}/plans/${planId}/confirm`, {
    method: "POST",
  });
export const cancelWorkspaceTask = (workspaceId, taskId) =>
  apiRequest(`${base(workspaceId)}/${taskId}/cancel`, { method: "POST" });
export const retryWorkspaceTask = (workspaceId, taskId) =>
  apiRequest(`${base(workspaceId)}/${taskId}/retry`, { method: "POST" });
export const retryWorkspaceTaskStep = (workspaceId, taskId, stepId) =>
  apiRequest(`${base(workspaceId)}/${taskId}/steps/${stepId}/retry`, {
    method: "POST",
  });
export const fetchWorkspaceTaskEvents = (workspaceId, taskId, afterId = 0) =>
  apiRequest(`${base(workspaceId)}/${taskId}/events?after_id=${afterId}`);

const TASK_EVENT_TYPES = [
  "task_draft_created",
  "clarification_requested",
  "clarification_answered",
  "plan_draft_created",
  "plan_version_created",
  "plan_confirmed",
  "task_claimed",
  "task_status_changed",
  "task_progress",
  "agent_started",
  "agent_completed",
  "agent_failed",
  "tool_started",
  "tool_completed",
  "tool_failed",
  "cancellation_requested",
  "task_cancelled",
  "task_retry_requested",
  "quality_retry_scheduled",
  "task_requeued",
  "task_failed",
  "task_completed",
];

export function openWorkspaceTaskEventStream(workspaceId, taskId, handlers) {
  const source = new EventSource(
    apiResourceUrl(`/api/v2${base(workspaceId)}/${taskId}/events/stream`),
    { withCredentials: true },
  );
  const handleEvent = (event) => {
    try {
      handlers.onEvent?.(JSON.parse(event.data));
    } catch {
      handlers.onError?.(new Error("SSE 事件格式无效"));
    }
  };
  TASK_EVENT_TYPES.forEach((eventType) => source.addEventListener(eventType, handleEvent));
  source.onopen = () => handlers.onOpen?.();
  source.onerror = () => handlers.onError?.(new Error("SSE 连接已断开"));
  return () => source.close();
}
