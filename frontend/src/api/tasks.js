const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function parseResponse(response) {
  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const message = data?.detail ?? "请求失败";
    throw new Error(message);
  }

  return data;
}

export async function createTask(payload) {
  const response = await fetch(`${API_BASE_URL}/api/tasks`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  return parseResponse(response);
}

export async function fetchTasks() {
  const response = await fetch(`${API_BASE_URL}/api/tasks`);
  return parseResponse(response);
}

export async function fetchTask(taskId) {
  const response = await fetch(`${API_BASE_URL}/api/tasks/${taskId}`);
  return parseResponse(response);
}

export async function fetchTaskTrace(taskId) {
  const response = await fetch(`${API_BASE_URL}/api/tasks/${taskId}/trace`);
  return parseResponse(response);
}
