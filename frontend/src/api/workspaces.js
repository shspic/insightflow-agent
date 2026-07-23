import { apiRequest } from "./client";

export const fetchWorkspaces = (includeDeleted = false) =>
  apiRequest(`/workspaces?include_deleted=${includeDeleted}`);
export const fetchWorkspace = (workspaceId) => apiRequest(`/workspaces/${workspaceId}`);
export const createWorkspace = (payload) => apiRequest("/workspaces", {
  method: "POST",
  body: JSON.stringify(payload),
});
export const updateWorkspace = (workspaceId, payload) =>
  apiRequest(`/workspaces/${workspaceId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
export const deleteWorkspace = (workspaceId) =>
  apiRequest(`/workspaces/${workspaceId}`, { method: "DELETE" });
export const restoreWorkspace = (workspaceId) =>
  apiRequest(`/workspaces/${workspaceId}/restore`, { method: "POST" });
