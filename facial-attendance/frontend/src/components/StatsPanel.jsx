import React from 'react';

/**
 * StatsPanel: Displays real-time metrics (Enrolled, Eligible, Present, Remaining).
 * All counts derived directly from backend state.
 */
export function StatsPanel({ counts = { enrolled: 0, eligible: 0, present: 0, remaining: 0 }, timezone = 'Local' }) {
  const cards = [
    { label: 'ENROLLED', value: counts.enrolled ?? 0, color: 'card-enrolled' },
    { label: 'ELIGIBLE', value: counts.eligible ?? 0, color: 'card-eligible' },
    { label: 'PRESENT', value: counts.present ?? 0, color: 'card-present' },
    { label: 'REMAINING', value: counts.remaining ?? 0, color: 'card-remaining' },
  ];

  return (
    <div className="stats-panel" data-testid="stats-panel">
      <div className="stats-grid">
        {cards.map((c) => (
          <div key={c.label} className={`stat-card ${c.color}`} data-testid={`stat-${c.label.toLowerCase()}`}>
            <span className="stat-label">{c.label}</span>
            <span className="stat-value">{c.value}</span>
          </div>
        ))}
      </div>
      <div className="stats-footer">
        <span className="timezone-text">Session Timezone: {timezone}</span>
      </div>
    </div>
  );
}
