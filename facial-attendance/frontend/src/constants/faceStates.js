/**
 * Face states and their corresponding box colors, badges, and labels.
 * Single source of truth for all face rendering in the React UI.
 */

export const FACE_STATES = {
  TRACKING: 'tracking',
  STABILIZING: 'stabilizing',
  EXCESSIVE_MOVEMENT: 'excessive_movement',
  TIMEOUT: 'timeout',
  STABLE: 'stable',
  RECOGNIZING: 'recognizing',
  VERIFYING: 'verifying',
  CONFIRMED: 'confirmed',
  ALREADY_MARKED: 'already_marked',
  UNKNOWN: 'unknown',
  WRITE_FAILED: 'write_failed',
};

export const FACE_STATE_CONFIG = {
  [FACE_STATES.TRACKING]: {
    color: '#00d7ff', // Cyan / Light Blue
    badgeBg: '#00d7ff',
    badgeText: '#000000',
    label: 'Tracking Face',
    description: 'Face detected. Tracking initialized.',
  },
  [FACE_STATES.STABILIZING]: {
    color: '#f39c12', // Amber / Orange
    badgeBg: '#f39c12',
    badgeText: '#000000',
    label: 'Stabilizing',
    description: 'Please stay still...',
  },
  [FACE_STATES.EXCESSIVE_MOVEMENT]: {
    color: '#e74c3c', // Red-Orange Warning
    badgeBg: '#e74c3c',
    badgeText: '#ffffff',
    label: 'Movement Detected',
    description: 'Please stay still - face movement detected',
  },
  [FACE_STATES.TIMEOUT]: {
    color: '#e67e22', // Amber Warning
    badgeBg: '#e67e22',
    badgeText: '#ffffff',
    label: 'Stability Timeout',
    description: 'Unable to stabilize face. Please position yourself and try again',
  },
  [FACE_STATES.STABLE]: {
    color: '#3498db', // Blue
    badgeBg: '#3498db',
    badgeText: '#ffffff',
    label: 'Face Stable',
    description: 'Face stable - verifying identity...',
  },
  [FACE_STATES.RECOGNIZING]: {
    color: '#9b59b6', // Purple
    badgeBg: '#9b59b6',
    badgeText: '#ffffff',
    label: 'Verifying Identity',
    description: 'Face stable - verifying identity...',
    isVerifying: true,
  },
  [FACE_STATES.VERIFYING]: {
    color: '#9b59b6',
    badgeBg: '#9b59b6',
    badgeText: '#ffffff',
    label: 'Verifying Identity',
    description: 'Face stable - verifying identity...',
    isVerifying: true,
  },
  [FACE_STATES.CONFIRMED]: {
    color: '#2ecc71', // Bright Green
    badgeBg: '#2ecc71',
    badgeText: '#ffffff',
    label: 'Confirmed',
    description: 'Attendance marked successfully',
  },
  [FACE_STATES.ALREADY_MARKED]: {
    color: '#27ae60', // Emerald Green
    badgeBg: '#27ae60',
    badgeText: '#ffffff',
    label: 'Already Marked',
    description: 'Already marked',
  },
  [FACE_STATES.UNKNOWN]: {
    color: '#e74c3c', // Crimson Red
    badgeBg: '#e74c3c',
    badgeText: '#ffffff',
    label: 'Unknown Face',
    description: 'Unknown face - attendance not marked',
  },
  [FACE_STATES.WRITE_FAILED]: {
    color: '#c0392b', // Dark Red
    badgeBg: '#c0392b',
    badgeText: '#ffffff',
    label: 'Write Error',
    description: 'Excel write failure - retryable',
  },
};

/**
 * Helper to get styling for a given state string safely.
 */
export function getFaceStateConfig(stateStr) {
  const normState = (stateStr || '').toLowerCase().trim();
  return FACE_STATE_CONFIG[normState] || FACE_STATE_CONFIG[FACE_STATES.TRACKING];
}
