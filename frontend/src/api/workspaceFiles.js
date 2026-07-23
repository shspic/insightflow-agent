import { apiRequest } from "./client";

const base = (workspaceId) => `/workspaces/${workspaceId}/files`;

export const fetchWorkspaceFiles = (workspaceId) => apiRequest(base(workspaceId));
export const uploadWorkspaceFile = (workspaceId, file) => {
  const formData = new FormData();
  formData.append("file", file);
  return apiRequest(base(workspaceId), { method: "POST", body: formData });
};
export const removeWorkspaceFile = (workspaceId, fileId) =>
  apiRequest(`${base(workspaceId)}/${fileId}`, { method: "DELETE" });
export const parseWorkspaceFile = (workspaceId, fileId) =>
  apiRequest(`${base(workspaceId)}/${fileId}/parse`, { method: "POST" });
export const analyzeWorkspaceFile = (workspaceId, fileId) =>
  apiRequest(`${base(workspaceId)}/${fileId}/analyze`, { method: "POST" });
export const chartWorkspaceFile = (workspaceId, fileId) =>
  apiRequest(`${base(workspaceId)}/${fileId}/charts`, { method: "POST" });
export const indexWorkspacePdf = (workspaceId, fileId) =>
  apiRequest(`${base(workspaceId)}/${fileId}/index`, { method: "POST" });
export const ocrWorkspaceFile = (workspaceId, fileId) =>
  apiRequest(`${base(workspaceId)}/${fileId}/ocr`, { method: "POST" });
