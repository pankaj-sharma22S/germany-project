import React from 'react';
import { useNavigate } from 'react-router-dom';

/**
 * RecentAttendance: Lists recent confirmed marks persisted to Excel for active session.
 * Each row includes a "View details" button to navigate to the student's detail page.
 */
export function RecentAttendance({ items = [], currentSessionId = '', onViewDetails = null }) {
  let navigate = null;
  try {
    navigate = useNavigate();
  } catch {
    // Fallback if rendered outside Router context in simple unit tests
  }

  const handleView = (item) => {
    const sess = item.session_id || currentSessionId || '';
    if (onViewDetails) {
      onViewDetails(item.student_id, sess);
    } else if (navigate) {
      const query = sess ? `?session=${encodeURIComponent(sess)}` : '';
      navigate(`/students/${encodeURIComponent(item.student_id)}${query}`);
    }
  };

  return (
    <div className="recent-attendance-panel" data-testid="recent-attendance">
      <div className="panel-header">
        <h4>Recent Attendance Marks</h4>
        <span className="badge-confirmed-count">{items.length} logged</span>
      </div>

      <div className="attendance-list">
        {items.length === 0 ? (
          <div className="empty-state" data-testid="empty-attendance">
            <span>No attendance marked yet</span>
          </div>
        ) : (
          items.map((item, idx) => (
            <div
              key={`${item.student_id}-${item.time || idx}`}
              className="attendance-item"
              data-testid="attendance-item"
            >
              <div className="item-meta">
                <span className="item-time">[{item.time}]</span>
                <span className="item-id">{item.student_id}</span>
                <span className="item-name">{item.name}</span>
              </div>
              <div className="item-details">
                {item.match_score > 0 && (
                  <span className="item-score" title="Cosine Similarity Score">
                    Sim: {Number(item.match_score).toFixed(2)}
                  </span>
                )}
                <span
                  className={`status-pill ${
                    item.status === 'Present' ? 'pill-present' : 'pill-absent'
                  }`}
                >
                  {item.status}
                </span>
                <button
                  type="button"
                  className="btn-view-details"
                  onClick={() => handleView(item)}
                  data-testid="btn-view-details"
                  aria-label={`View details for ${item.name}`}
                >
                  View details
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
