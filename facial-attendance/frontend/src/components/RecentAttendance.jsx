import React from 'react';

/**
 * RecentAttendance: Lists recent confirmed marks persisted to Excel for active session.
 */
export function RecentAttendance({ items = [] }) {
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
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
