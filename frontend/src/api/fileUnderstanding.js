import { apiRequest } from "./client";

const workspaceBase = (workspaceId) => `/workspaces/${workspaceId}`;

export const uploadWorkspaceFilesBatch = (workspaceId, files) => {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  return apiRequest(`${workspaceBase(workspaceId)}/files/batch`, {
    method: "POST",
    body: formData,
  });
};

export const understandWorkspaceFile = (workspaceId, fileId, options = {}) =>
  apiRequest(`${workspaceBase(workspaceId)}/files/${fileId}/understand`, {
    method: "POST",
    body: JSON.stringify(options),
  });

export const understandWorkspaceFiles = (workspaceId, fileIds, options = {}) =>
  apiRequest(`${workspaceBase(workspaceId)}/files/understand`, {
    method: "POST",
    body: JSON.stringify({ file_ids: fileIds, options }),
  });

export const fetchWorkspaceFileProfile = (workspaceId, fileId) =>
  apiRequest(`${workspaceBase(workspaceId)}/files/${fileId}/profile`);

export const updateWorkspaceFileProfile = (workspaceId, fileId, payload) =>
  apiRequest(`${workspaceBase(workspaceId)}/files/${fileId}/profile`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const discoverWorkspaceFileRelations = (workspaceId, payload = {}) =>
  apiRequest(`${workspaceBase(workspaceId)}/file-relations/discover`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const fetchWorkspaceFileRelations = (workspaceId, status = null) =>
  apiRequest(
    `${workspaceBase(workspaceId)}/file-relations${status ? `?status=${encodeURIComponent(status)}` : ""}`,
  );

export const updateWorkspaceFileRelation = (workspaceId, relationId, payload) =>
  apiRequest(`${workspaceBase(workspaceId)}/file-relations/${relationId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const previewWorkspaceContext = (workspaceId, fileIds = null) =>
  apiRequest(`${workspaceBase(workspaceId)}/context-preview`, {
    method: "POST",
    body: JSON.stringify({ file_ids: fileIds }),
  });
