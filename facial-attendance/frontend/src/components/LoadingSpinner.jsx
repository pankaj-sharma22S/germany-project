import React from 'react';

/**
 * LoadingSpinner: displayed only when backend state is 'verifying' or 'recognizing'.
 * Driven strictly by actual backend processing state.
 */
export function LoadingSpinner({ label = 'Verifying Identity...' }) {
  return (
    <div className="loading-spinner-container" data-testid="loading-spinner">
      <div className="spinner-ring" />
      <span className="spinner-text">{label}</span>
    </div>
  );
}
