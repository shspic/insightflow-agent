import { apiRequest } from "./client";

export const fetchMyUsage = () => apiRequest("/usage/me");
export const fetchUsageSummary = () => apiRequest("/admin/usage/summary");
export const fetchUserUsage = () => apiRequest("/admin/usage/users");
export const fetchAdminTasks = () => apiRequest("/admin/tasks");
export const fetchWorkers = () => apiRequest("/admin/workers");
export const fetchModelUsage = () => apiRequest("/admin/model-usage");
export const fetchFeedback = () => apiRequest("/admin/feedback");
export const fetchPromptVersions = () => apiRequest("/admin/prompt-versions");
export const activatePrompt = (id) =>
  apiRequest(`/admin/prompt-versions/${id}/activate`, { method: "POST" });
export const fetchEvaluationRuns = () => apiRequest("/admin/evaluations/runs");
export const runDeterministicEvaluation = () =>
  apiRequest("/admin/evaluations/runs", {
    method: "POST",
    body: JSON.stringify({ dataset: "v2-core", mode: "deterministic" }),
  });
export const runCleanupDryRun = () =>
  apiRequest("/admin/cleanup", {
    method: "POST",
    body: JSON.stringify({ dry_run: true }),
  });
