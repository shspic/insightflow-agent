const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function parseResponse(response) {
  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const message = data?.detail ?? "请求失败";
    throw new Error(message);
  }

  return data;
}

export async function uploadFile(file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/files/upload`, {
    method: "POST",
    body: formData,
  });

  return parseResponse(response);
}

export async function fetchFiles() {
  const response = await fetch(`${API_BASE_URL}/api/files`);
  return parseResponse(response);
}

export async function parseFile(fileId) {
  const response = await fetch(`${API_BASE_URL}/api/files/${fileId}/parse`, {
    method: "POST",
  });

  return parseResponse(response);
}
