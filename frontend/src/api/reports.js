import { apiRequest, apiResourceUrl } from "./client";

const base = (workspaceId, taskId) =>
  `/workspaces/${workspaceId}/tasks/${taskId}`;

export const fetchReportTemplates = () => apiRequest("/report-templates");
export const fetchReportVersions = (workspaceId, taskId) =>
  apiRequest(`${base(workspaceId, taskId)}/reports`);
export const exportReport = (workspaceId, taskId, reportId, format) =>
  apiRequest(
    `${base(workspaceId, taskId)}/reports/${reportId}/exports?format=${encodeURIComponent(format)}`,
    { method: "POST" },
  );
export const deleteReportVersion = (workspaceId, taskId, reportId) =>
  apiRequest(`${base(workspaceId, taskId)}/reports/${reportId}`, { method: "DELETE" });
export const setCurrentReportVersion = (workspaceId, taskId, reportId) =>
  apiRequest(`${base(workspaceId, taskId)}/reports/${reportId}/current`, { method: "POST" });
export const createReportFeedback = (workspaceId, taskId, payload) =>
  apiRequest(`${base(workspaceId, taskId)}/feedback`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const regenerateReport = (workspaceId, taskId, payload) =>
  apiRequest(`${base(workspaceId, taskId)}/reports/regenerate`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const reportDownloadUrl = (path) => apiResourceUrl(path);
