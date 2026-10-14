/**
 * HTTP Client for local FastAPI backend.
 * Localhost 127.0.0.1 binding only.
 */

const API_BASE_URL = 'http://127.0.0.1:8000';

async function handleResponse(response) {
  if (!response.ok) {
    let errorDetail = response.statusText;
    try {
      const errJson = await response.json();
      errorDetail = errJson.detail || errJson.message || JSON.stringify(errJson);
    } catch {
      // response wasn't JSON
    }
    throw new Error(errorDetail);
  }
  return response.json();
}

export const apiClient = {
  async getStatus() {
    const res = await fetch(`${API_BASE_URL}/api/status`);
    return handleResponse(res);
  },

  async startCamera() {
    const res = await fetch(`${API_BASE_URL}/api/camera/start`, { method: 'POST' });
    return handleResponse(res);
  },

  async stopCamera() {
    const res = await fetch(`${API_BASE_URL}/api/camera/stop`, { method: 'POST' });
    return handleResponse(res);
  },

  async startSession(sessionId = null) {
    const res = await fetch(`${API_BASE_URL}/api/session/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(sessionId ? { session_id: sessionId } : {}),
    });
    return handleResponse(res);
  },

  async stopSession() {
    const res = await fetch(`${API_BASE_URL}/api/session/stop`, { method: 'POST' });
    return handleResponse(res);
  },

  async getStudents() {
    const res = await fetch(`${API_BASE_URL}/api/students`);
    return handleResponse(res);
  },

  async enrollStudent(studentId, name, imageFile) {
    const formData = new FormData();
    formData.append('student_id', studentId);
    formData.append('name', name);
    formData.append('image', imageFile);

    const res = await fetch(`${API_BASE_URL}/api/students`, {
      method: 'POST',
      body: formData,
    });
    return handleResponse(res);
  },

  async getRecentAttendance() {
    const res = await fetch(`${API_BASE_URL}/api/attendance/recent`);
    return handleResponse(res);
  },
};
