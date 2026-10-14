import React from 'react';

/**
 * Controls: Action buttons for Camera, Session, and Student Enrollment.
 */
export function Controls({
  cameraActive,
  sessionActive,
  sessionId,
  onToggleCamera,
  onToggleSession,
  onOpenAddStudent,
  disabled = false,
}) {
  return (
    <div className="controls-panel" data-testid="controls-panel">
      <div className="controls-row">
        {/* Add Student Button */}
        <button
          className="btn btn-enroll"
          onClick={onOpenAddStudent}
          disabled={disabled}
          data-testid="btn-add-student"
        >
          <span className="btn-icon">+</span>
          <span>Add Student</span>
        </button>

        {/* Camera Toggle Button */}
        <button
          className={`btn ${cameraActive ? 'btn-danger' : 'btn-success'}`}
          onClick={onToggleCamera}
          disabled={disabled}
          data-testid="btn-toggle-camera"
        >
          <span className="btn-icon">{cameraActive ? '⏹' : '▶'}</span>
          <span>{cameraActive ? 'Stop Camera' : 'Start Camera'}</span>
        </button>

        {/* Session Toggle Button */}
        <button
          className={`btn ${sessionActive ? 'btn-warning' : 'btn-primary'}`}
          onClick={onToggleSession}
          disabled={disabled}
          data-testid="btn-toggle-session"
        >
          <span className="btn-icon">{sessionActive ? '⏹' : '▶'}</span>
          <span>{sessionActive ? 'Stop Session' : 'Start Session'}</span>
        </button>
      </div>

      <div className="controls-meta">
        <span className="meta-badge">
          Session:{' '}
          <strong className={sessionActive ? 'text-success' : 'text-muted'}>
            {sessionActive ? 'ACTIVE' : 'INACTIVE'}
          </strong>
        </span>
        {sessionId && sessionId !== 'None' && (
          <span className="meta-badge meta-session-id" title={sessionId}>
            ID: <code>{sessionId}</code>
          </span>
        )}
      </div>
    </div>
  );
}
