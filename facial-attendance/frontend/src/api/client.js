/**
 * HTTP Client for local FastAPI backend.
 * Localhost 127.0.0.1 binding only.
 */

const API_BASE_URL =
  typeof window !== 'undefined' && window.location.port !== '5173' && window.location.origin.startsWith('http')
    ? window.location.origin
    : 'http://127.0.0.1:8000';

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

  async enrollStudent(studentId, name, photoFile, idCardFile = null) {
    const formData = new FormData();
    formData.append('student_id', studentId);
    formData.append('name', name);
    formData.append('photo', photoFile);
    formData.append('image', photoFile); // backward compatibility
    if (idCardFile) {
      formData.append('id_card', idCardFile);
    }

    const res = await fetch(`${API_BASE_URL}/api/students`, {
      method: 'POST',
      body: formData,
    });
    return handleResponse(res);
  },

  async getStudentDetails(studentId, sessionId = null) {
    const url = new URL(`${API_BASE_URL}/api/students/${encodeURIComponent(studentId)}`);
    if (sessionId) {
      url.searchParams.set('session_id', sessionId);
    }
    const res = await fetch(url.toString());
    return handleResponse(res);
  },

  getStudentPhotoUrl(studentId) {
    return `${API_BASE_URL}/api/students/${encodeURIComponent(studentId)}/photo`;
  },

  getStudentIdCardUrl(studentId) {
    return `${API_BASE_URL}/api/students/${encodeURIComponent(studentId)}/id-card`;
  },

  async getRecentAttendance() {
    const res = await fetch(`${API_BASE_URL}/api/attendance/recent`);
    return handleResponse(res);
  },

  async getExcelSheetData(sheet = 'attendance') {
    const res = await fetch(`${API_BASE_URL}/api/excel/data?sheet=${encodeURIComponent(sheet)}`);
    return handleResponse(res);
  },

  getExcelDownloadUrl(fileName) {
    return `${API_BASE_URL}/api/excel/download/${encodeURIComponent(fileName)}`;
  },

  async deduplicateAttendance() {
    const res = await fetch(`${API_BASE_URL}/api/excel/deduplicate`, { method: 'POST' });
    return handleResponse(res);
  },

  async clearAllData() {
    const res = await fetch(`${API_BASE_URL}/api/admin/clear-data`, { method: 'POST' });
    return handleResponse(res);
  },
};

