export const API_BASE_URL = (import.meta.env?.VITE_API_BASE_URL || "").replace(/\/$/, "");
export const V2_API_BASE_URL = `${API_BASE_URL}/api/v2`;
