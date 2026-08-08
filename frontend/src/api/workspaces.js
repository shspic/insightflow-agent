import { apiRequest } from "./client";

export const fetchWorkspaces = (includeDeleted = false, workspaceType = "") => {
  const params = new URLSearchParams();
  params.set("include_deleted", String(includeDeleted));
  if (workspaceType) params.set("workspace_type", workspaceType);
  return apiRequest(`/workspaces?${params.toString()}`);
};
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
export const deleteWorkspace = (workspaceId, confirmationName) =>
  apiRequest(`/workspaces/${workspaceId}`, {
    method: "DELETE",
    body: JSON.stringify({ confirmation_name: confirmationName }),
  });
