import React from 'react';

/**
 * StabilityIndicator: Displays face stabilization countdown / percentage bar.
 * Uses exact progress sent from backend stability manager (0.0 to 1.0).
 */
export function StabilityIndicator({ progress = 0, message = '' }) {
  const percent = Math.min(100, Math.max(0, Math.round(progress * 100)));

  return (
    <div className="stability-indicator" data-testid="stability-indicator">
      <div className="stability-header">
        <span className="stability-title">Face Stability Progress</span>
        <span className="stability-percent">{percent}%</span>
      </div>
      <div className="progress-track">
        <div
          className="progress-fill"
          style={{ width: `${percent}%` }}
          data-testid="progress-bar-fill"
        />
      </div>
      {message && <div className="stability-hint">{message}</div>}
    </div>
  );
}
