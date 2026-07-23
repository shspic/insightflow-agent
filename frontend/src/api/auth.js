import { apiRequest } from "./client";

export const fetchCurrentUser = () => apiRequest("/auth/me");
export const login = (payload) => apiRequest("/auth/login", {
  method: "POST",
  body: JSON.stringify(payload),
});
export const register = (payload) => apiRequest("/auth/register", {
  method: "POST",
  body: JSON.stringify(payload),
});
export const logout = () => apiRequest("/auth/logout", { method: "POST" });
export const changePassword = (payload) => apiRequest("/auth/change-password", {
  method: "POST",
  body: JSON.stringify(payload),
});
export const submitPasswordReset = (payload) => apiRequest("/auth/password-reset-requests", {
  method: "POST",
  body: JSON.stringify(payload),
});
