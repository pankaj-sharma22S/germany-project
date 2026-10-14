import React, { useEffect, useState, useCallback } from 'react';
import { useStream } from './hooks/useStream';
import { apiClient } from './api/client';
import { VideoPanel } from './components/VideoPanel';
import { StatusBanner } from './components/StatusBanner';
import { Controls } from './components/Controls';
import { StatsPanel } from './components/StatsPanel';
import { RecentAttendance } from './components/RecentAttendance';
import { AddStudentModal } from './components/AddStudentModal';
import './styles/App.css';

export function App() {
  const stream = useStream();
  const [isAddStudentOpen, setIsAddStudentOpen] = useState(false);
  const [recentMarks, setRecentMarks] = useState([]);
  const [actionLoading, setActionLoading] = useState(false);
  const [appBannerMsg, setAppBannerMsg] = useState(null);

  // Fetch recent attendance marks from API
  const fetchRecentAttendance = useCallback(async () => {
    try {
      const res = await apiClient.getRecentAttendance();
      if (res && res.recent) {
        setRecentMarks(res.recent);
      }
    } catch (err) {
      // Ignore background poll errors if backend offline
    }
  }, []);

  useEffect(() => {
    fetchRecentAttendance();
    const interval = setInterval(fetchRecentAttendance, 3000);
    return () => clearInterval(interval);
  }, [fetchRecentAttendance]);

  // If a student is confirmed, refresh recent marks immediately
  useEffect(() => {
    const hasConfirmedFace = stream.faces.some((f) => f.state === 'confirmed');
    if (hasConfirmedFace) {
      fetchRecentAttendance();
    }
  }, [stream.faces, fetchRecentAttendance]);

  // Actions
  async function handleToggleCamera() {
    setActionLoading(true);
    try {
      if (stream.cameraActive) {
        await apiClient.stopCamera();
      } else {
        await apiClient.startCamera();
      }
    } catch (err) {
      setAppBannerMsg(`Camera Error: ${err.message}`);
      setTimeout(() => setAppBannerMsg(null), 4000);
    } finally {
      setActionLoading(false);
    }
  }

  async function handleToggleSession() {
    setActionLoading(true);
    try {
      if (stream.sessionActive) {
        const res = await apiClient.stopSession();
        setAppBannerMsg(`Session Stopped: ${res.present} Present, ${res.absent} Absent`);
      } else {
        const res = await apiClient.startSession();
        setAppBannerMsg(`Session Started: ${res.session_id}`);
      }
      fetchRecentAttendance();
      setTimeout(() => setAppBannerMsg(null), 4000);
    } catch (err) {
      setAppBannerMsg(`Session Error: ${err.message}`);
      setTimeout(() => setAppBannerMsg(null), 4000);
    } finally {
      setActionLoading(false);
    }
  }

  function handleEnrollSuccess(studentId, name) {
    setAppBannerMsg(`Student ${name} (${studentId}) enrolled successfully!`);
    fetchRecentAttendance();
    setTimeout(() => setAppBannerMsg(null), 5000);
  }

  const activeMessage = appBannerMsg || stream.message;

  return (
    <div className="app-container">
      {/* Top Navigation / Brand Header */}
      <header className="app-header">
        <div className="brand-section">
          <span className="brand-icon">👁</span>
          <h1>Facial Attendance System</h1>
        </div>
        <div className="connection-badge" data-testid="connection-status">
          <span
            className={`indicator-dot ${
              stream.connected ? 'dot-connected' : 'dot-disconnected'
            }`}
          />
          <span>{stream.connected ? 'Connected' : 'Disconnected'}</span>
        </div>
      </header>

      {/* Main Workspace Layout */}
      <main className="app-main">
        {/* Left Video Stream & Primary Controls */}
        <section className="stream-section">
          <StatusBanner
            message={activeMessage}
            connected={stream.connected}
          />

          <VideoPanel
            frame={stream.frame}
            frameSize={stream.frameSize}
            faces={stream.faces}
            cameraActive={stream.cameraActive}
            connected={stream.connected}
            onStartCamera={handleToggleCamera}
          />

          <Controls
            cameraActive={stream.cameraActive}
            sessionActive={stream.sessionActive}
            sessionId={stream.sessionId}
            onToggleCamera={handleToggleCamera}
            onToggleSession={handleToggleSession}
            onOpenAddStudent={() => setIsAddStudentOpen(true)}
            disabled={actionLoading || !stream.connected}
          />
        </section>

        {/* Right Sidebar Stats & Attendance Feed */}
        <aside className="sidebar-section">
          <StatsPanel counts={stream.counts} />
          <RecentAttendance items={recentMarks} />
        </aside>
      </main>

      {/* Runtime Enrollment Modal */}
      <AddStudentModal
        isOpen={isAddStudentOpen}
        onClose={() => setIsAddStudentOpen(false)}
        onEnrollSuccess={handleEnrollSuccess}
        enrollApi={apiClient.enrollStudent}
      />
    </div>
  );
}

export default App;
