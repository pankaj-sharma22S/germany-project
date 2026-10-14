import React from 'react';
import { NavLink } from 'react-router-dom';

/**
 * Top Navbar component with page navigation links and real-time status.
 */
export function Navbar({ connected = null }) {
  return (
    <header className="app-header">
      <div className="brand-section">
        <span className="brand-icon">👁</span>
        <h1>Facial Attendance System</h1>
      </div>

      <nav className="header-nav-links">
        <NavLink
          to="/"
          className={({ isActive }) =>
            `nav-link-btn ${isActive ? 'nav-link-active' : ''}`
          }
          end
        >
          <span className="nav-icon">📷</span>
          <span>Live Monitor</span>
        </NavLink>

        <NavLink
          to="/excel"
          className={({ isActive }) =>
            `nav-link-btn ${isActive ? 'nav-link-active' : ''}`
          }
        >
          <span className="nav-icon">📊</span>
          <span>Interactive Excel</span>
        </NavLink>
      </nav>

      {connected !== null && (
        <div className="connection-badge" data-testid="connection-status">
          <span
            className={`indicator-dot ${
              connected ? 'dot-connected' : 'dot-disconnected'
            }`}
          />
          <span>{connected ? 'Connected' : 'Disconnected'}</span>
        </div>
      )}
    </header>
  );
}

export default Navbar;
