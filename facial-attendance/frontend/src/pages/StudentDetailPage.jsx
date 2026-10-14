import React, { useEffect, useState } from 'react';
import { useParams, useSearchParams, Link } from 'react-router-dom';
import { apiClient } from '../api/client';
import { ImageCard } from '../components/ImageCard';
import { LoadingSpinner } from '../components/LoadingSpinner';

/**
 * StudentDetailPage Component:
 * Displays student biometric record, reference photo, ID card, and session attendance.
 * Route: /students/:studentId?session=<session_id>
 */
export function StudentDetailPage() {
  const { studentId } = useParams();
  const [searchParams] = useSearchParams();
  const sessionId = searchParams.get('session');

  const [student, setStudent] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let isMounted = true;
    setLoading(true);
    setError(null);

    apiClient
      .getStudentDetails(studentId, sessionId)
      .then((data) => {
        if (isMounted) {
          setStudent(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err.message || 'Failed to load student details');
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [studentId, sessionId]);

  if (loading) {
    return (
      <div className="detail-page-container" data-testid="detail-page-loading">
        <div className="detail-loading-box">
          <LoadingSpinner text={`Loading details for Student ${studentId}...`} />
        </div>
      </div>
    );
  }

  if (error || !student) {
    return (
      <div className="detail-page-container" data-testid="detail-page-error">
        <div className="detail-card detail-card-error">
          <div className="error-icon-large">✕</div>
          <h2>Student Not Found</h2>
          <p className="error-message-text">{error || `Student '${studentId}' was not found in the registry.`}</p>
          <Link to="/" className="btn btn-secondary btn-back-home" data-testid="btn-back-home">
            ← Back to Live Attendance
          </Link>
        </div>
      </div>
    );
  }

  const attendance = student.attendance;
  const isPresent = attendance && attendance.status === 'Present';
  const hasAttendance = attendance && attendance.status && attendance.status !== 'Not marked in this session';

  return (
    <div className="detail-page-container" data-testid="student-detail-page">
      {/* Top Header Navigation */}
      <div className="detail-header-bar">
        <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
          <Link to="/" className="btn-back-link" data-testid="link-back-live">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="19" y1="12" x2="5" y2="12" />
              <polyline points="12 19 5 12 12 5" />
            </svg>
            Live Monitor
          </Link>
          <Link to="/excel" className="btn-back-link" style={{ color: '#64b5f6' }}>
            <span>📊 Excel Sheets</span>
          </Link>
        </div>
        <div className="detail-student-badge">
          <span className="badge-sid">{student.student_id}</span>
          <span className="badge-name">{student.name}</span>
        </div>
      </div>

      <div className="detail-content-grid">
        {/* Left Column: Student Bio & Attendance Card */}
        <div className="detail-left-column">
          <div className="detail-card student-bio-card">
            <h3>Student Profile</h3>
            <div className="bio-field-row">
              <span className="bio-label">Student ID:</span>
              <span className="bio-value" data-testid="student-id-val">{student.student_id}</span>
            </div>
            <div className="bio-field-row">
              <span className="bio-label">Full Name:</span>
              <span className="bio-value" data-testid="student-name-val">{student.name}</span>
            </div>
            <div className="bio-field-row">
              <span className="bio-label">Biometric Status:</span>
              <span className="bio-value text-success">✓ Enrolled in Buffalo_S Index</span>
            </div>
            <div className="bio-field-row">
              <span className="bio-label">ID Card Status:</span>
              <span className={`bio-value ${student.has_id_card ? 'text-success' : 'text-muted'}`}>
                {student.has_id_card ? '✓ Verified on File' : 'No ID card on file'}
              </span>
            </div>
          </div>

          {/* Session Attendance Record */}
          <div className="detail-card attendance-record-card">
            <h3>Session Attendance</h3>
            {sessionId && (
              <div className="session-id-indicator">
                <span>Session: </span>
                <strong>{sessionId}</strong>
              </div>
            )}

            {!hasAttendance ? (
              <div className="attendance-not-marked" data-testid="status-not-marked">
                <span className="pill-absent">Not marked in this session</span>
                <p className="attendance-hint">This student has not been verified present for session {sessionId || 'N/A'}.</p>
              </div>
            ) : (
              <div className="attendance-marked-details" data-testid="attendance-marked-details">
                <div className="attendance-status-banner">
                  <span className={`status-pill ${isPresent ? 'pill-present' : 'pill-absent'}`}>
                    {attendance.status}
                  </span>
                </div>

                <div className="attendance-grid-meta">
                  <div className="meta-box">
                    <span className="meta-label">Date</span>
                    <span className="meta-value">{attendance.date || 'N/A'}</span>
                  </div>
                  <div className="meta-box">
                    <span className="meta-label">Time</span>
                    <span className="meta-value">{attendance.time || 'N/A'}</span>
                  </div>
                  <div className="meta-box">
                    <span className="meta-label">Similarity</span>
                    <span className="meta-value score-highlight">
                      {attendance.similarity != null ? Number(attendance.similarity).toFixed(4) : 'N/A'}
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Visual Biometrics (Reference Face + ID Card) */}
        <div className="detail-right-column">
          <div className="images-container-grid">
            {/* Reference Photo Card */}
            <ImageCard
              title="Reference Face Photo"
              src={apiClient.getStudentPhotoUrl(student.student_id)}
              alt={`Reference photo of ${student.name}`}
              placeholderText="No reference photo on file"
              hasImage={student.has_photo}
            />

            {/* ID Card Image Card */}
            <ImageCard
              title="Student ID Card"
              src={apiClient.getStudentIdCardUrl(student.student_id)}
              alt={`ID card of ${student.name}`}
              placeholderText="No ID card on file"
              hasImage={student.has_id_card}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
