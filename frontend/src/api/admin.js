import { apiRequest } from "./client";

export const fetchInviteCodes = () => apiRequest("/admin/invite-codes");
export const createInviteCode = (payload) => apiRequest("/admin/invite-codes", {
  method: "POST",
  body: JSON.stringify(payload),
});
export const updateInviteCode = (id, payload) => apiRequest(`/admin/invite-codes/${id}`, {
  method: "PATCH",
  body: JSON.stringify(payload),
});
export const rotateInviteCode = (id) =>
  apiRequest(`/admin/invite-codes/${id}/rotate`, { method: "POST" });
export const fetchResetRequests = () =>
  apiRequest("/admin/password-reset-requests?status=pending");
export const rejectResetRequest = (id, adminNote) =>
  apiRequest(`/admin/password-reset-requests/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ admin_note: adminNote || null }),
  });
export const issueTemporaryPassword = (id, adminNote) =>
  apiRequest(`/admin/password-reset-requests/${id}/issue-temporary-password`, {
    method: "POST",
    body: JSON.stringify({ admin_note: adminNote || null }),
  });
export const fetchUsers = () => apiRequest("/admin/users");
export const updateUserStatus = (id, status) => apiRequest(`/admin/users/${id}/status`, {
  method: "PATCH",
  body: JSON.stringify({ status }),
});
export const fetchAuditLogs = () => apiRequest("/admin/audit-logs");
