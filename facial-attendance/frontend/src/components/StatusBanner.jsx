import React from 'react';

/**
 * StatusBanner: Displays dynamic backend feedback messages, warnings, and alerts.
 */
export function StatusBanner({ message, connected, isWarning, isSuccess, isError }) {
  if (!connected) {
    return (
      <div className="status-banner banner-disconnected" data-testid="status-banner-disconnected">
        <span className="banner-icon">⚠</span>
        <span>Backend Disconnected. Reconnecting to local stream (127.0.0.1:8000)...</span>
      </div>
    );
  }

  if (!message) return null;

  // Determine banner tone
  let toneClass = 'banner-neutral';
  let icon = 'ℹ';

  const lower = message.toLowerCase();
  if (lower.includes('marked successfully') || isSuccess) {
    toneClass = 'banner-success';
    icon = '✓';
  } else if (lower.includes('movement detected') || lower.includes('position yourself') || isWarning) {
    toneClass = 'banner-warning';
    icon = '⚠';
  } else if (lower.includes('unknown face') || lower.includes('error') || lower.includes('failure') || isError) {
    toneClass = 'banner-danger';
    icon = '✕';
  } else if (lower.includes('already marked')) {
    toneClass = 'banner-info';
    icon = '✓';
  } else if (lower.includes('verifying')) {
    toneClass = 'banner-processing';
    icon = '⋯';
  }

  return (
    <div className={`status-banner ${toneClass}`} data-testid="status-banner">
      <span className="banner-icon">{icon}</span>
      <span className="banner-text">{message}</span>
    </div>
  );
}
