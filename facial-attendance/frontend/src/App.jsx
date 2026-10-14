import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { LiveAttendancePage } from './pages/LiveAttendancePage';
import { StudentDetailPage } from './pages/StudentDetailPage';
import { ExcelViewerPage } from './pages/ExcelViewerPage';
import './styles/App.css';

/**
 * App: Top-level router configuring:
 * - Live Attendance screen at '/'
 * - Interactive Excel spreadsheet viewer at '/excel'
 * - Student Biometric Detail page at '/students/:studentId'
 */
export function App() {
  return (
    <BrowserRouter>
      <div className="app-container">
        <Routes>
          <Route path="/" element={<LiveAttendancePage />} />
          <Route path="/excel" element={<ExcelViewerPage />} />
          <Route path="/students/:studentId" element={<StudentDetailPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}

export default App;
