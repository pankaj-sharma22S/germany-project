import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { apiClient } from '../api/client';
import { Navbar } from '../components/Navbar';
import { LoadingSpinner } from '../components/LoadingSpinner';

/**
 * ExcelViewerPage: Interactive real-time Excel spreadsheet browser.
 * Reads directly from data/attendance.xlsx and data/students.xlsx on disk.
 */
export function ExcelViewerPage() {
  const [activeSheet, setActiveSheet] = useState('attendance'); // 'attendance' | 'students'
  const [sheetData, setSheetData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [autoSync, setAutoSync] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL'); // 'ALL' | 'Present' | 'Absent'
  const [dateFilter, setDateFilter] = useState('ALL');
  const [sortField, setSortField] = useState(null);
  const [sortDirection, setSortDirection] = useState('asc'); // 'asc' | 'desc'
  const [isClearModalOpen, setIsClearModalOpen] = useState(false);
  const [clearLoading, setClearLoading] = useState(false);
  const [toastMessage, setToastMessage] = useState(null);

  // Show temporary toast banner
  const showToast = useCallback((msg, durationMs = 4000) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), durationMs);
  }, []);

  // Fetch live Excel workbook data
  const fetchSheetData = useCallback(
    async (isSilent = false) => {
      if (!isSilent) setLoading(true);
      setError(null);
      try {
        const data = await apiClient.getExcelSheetData(activeSheet);
        setSheetData(data);
      } catch (err) {
        setError(err.message || 'Failed to read Excel data.');
      } finally {
        if (!isSilent) setLoading(false);
      }
    },
    [activeSheet]
  );

  // Initial fetch and on activeSheet change
  useEffect(() => {
    fetchSheetData(false);
  }, [fetchSheetData]);

  // Auto-sync polling every 3 seconds if enabled
  useEffect(() => {
    if (!autoSync) return;
    const timer = setInterval(() => {
      fetchSheetData(true);
    }, 3000);
    return () => clearInterval(timer);
  }, [autoSync, fetchSheetData]);

  // Handle column sort toggle
  const handleSort = (field) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
  };

  // Distinct dates in attendance records for filtering
  const distinctDates = useMemo(() => {
    if (!sheetData || !sheetData.rows) return [];
    const dates = new Set();
    sheetData.rows.forEach((r) => {
      if (r.date) dates.add(String(r.date).trim());
    });
    return Array.from(dates).sort();
  }, [sheetData]);

  // Filtered and sorted rows
  const displayedRows = useMemo(() => {
    if (!sheetData || !sheetData.rows) return [];
    let list = [...sheetData.rows];

    // Search query filter across all fields
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      list = list.filter((row) =>
        Object.values(row).some((val) =>
          String(val).toLowerCase().includes(q)
        )
      );
    }

    // Status filter (for attendance sheet)
    if (activeSheet === 'attendance' && statusFilter !== 'ALL') {
      list = list.filter(
        (row) => String(row.status || '').toLowerCase() === statusFilter.toLowerCase()
      );
    }

    // Date filter (for attendance sheet)
    if (activeSheet === 'attendance' && dateFilter !== 'ALL') {
      list = list.filter((row) => String(row.date || '').trim() === dateFilter);
    }

    // Sort
    if (sortField) {
      list.sort((a, b) => {
        let va = a[sortField];
        let vb = b[sortField];

        if (va === undefined || va === null) va = '';
        if (vb === undefined || vb === null) vb = '';

        if (typeof va === 'number' && typeof vb === 'number') {
          return sortDirection === 'asc' ? va - vb : vb - va;
        }

        const sa = String(va).toLowerCase();
        const sb = String(vb).toLowerCase();
        if (sa < sb) return sortDirection === 'asc' ? -1 : 1;
        if (sa > sb) return sortDirection === 'asc' ? 1 : -1;
        return 0;
      });
    }

    return list;
  }, [sheetData, searchQuery, statusFilter, dateFilter, sortField, sortDirection, activeSheet]);

  // Handle Deduplicate action
  async function handleDeduplicate() {
    try {
      const res = await apiClient.deduplicateAttendance();
      showToast(`Deduplication complete: ${res.removed_rows} redundant rows removed.`);
      fetchSheetData(false);
    } catch (err) {
      showToast(`Deduplication error: ${err.message}`);
    }
  }

  // Handle Clear / Start Fresh
  async function handleConfirmClear() {
    setClearLoading(true);
    try {
      const res = await apiClient.clearAllData();
      showToast(res.message || 'System data cleared! Ready for fresh start.');
      setIsClearModalOpen(false);
      fetchSheetData(false);
    } catch (err) {
      showToast(`Clear error: ${err.message}`);
    } finally {
      setClearLoading(false);
    }
  }

  const currentFileName = activeSheet === 'attendance' ? 'attendance.xlsx' : 'students.xlsx';
  const downloadUrl = apiClient.getExcelDownloadUrl(currentFileName);
  const summary = sheetData?.summary || {};

  return (
    <div className="excel-page-container">
      <Navbar />

      {/* Toast Notification */}
      {toastMessage && (
        <div className="excel-toast-banner" role="status">
          <span>{toastMessage}</span>
          <button className="toast-close-btn" onClick={() => setToastMessage(null)}>
            ×
          </button>
        </div>
      )}

      <main className="excel-main-content">
        {/* Top Control Bar & Sheet Tabs */}
        <section className="excel-top-bar">
          <div className="sheet-tabs">
            <button
              className={`sheet-tab-btn ${activeSheet === 'attendance' ? 'tab-active' : ''}`}
              onClick={() => {
                setActiveSheet('attendance');
                setSortField(null);
                setSearchQuery('');
              }}
            >
              <span className="tab-icon">📋</span>
              <span>Attendance Sheet</span>
              <span className="tab-badge">
                {activeSheet === 'attendance' && sheetData?.summary?.total_rows !== undefined
                  ? sheetData.summary.total_rows
                  : ''}
              </span>
            </button>

            <button
              className={`sheet-tab-btn ${activeSheet === 'students' ? 'tab-active' : ''}`}
              onClick={() => {
                setActiveSheet('students');
                setSortField(null);
                setSearchQuery('');
              }}
            >
              <span className="tab-icon">👥</span>
              <span>Students Registry</span>
              <span className="tab-badge">
                {activeSheet === 'students' && sheetData?.summary?.total_students !== undefined
                  ? sheetData.summary.total_students
                  : ''}
              </span>
            </button>
          </div>

          {/* Action Toolbar */}
          <div className="excel-action-buttons">
            <label className="auto-sync-toggle" title="Toggle automatic background sync with disk">
              <input
                type="checkbox"
                checked={autoSync}
                onChange={(e) => setAutoSync(e.target.checked)}
              />
              <span className="sync-dot" />
              <span>Auto-sync (3s)</span>
            </label>

            <button
              className="action-btn-secondary"
              onClick={() => fetchSheetData(false)}
              disabled={loading}
              title="Read latest file from disk now"
            >
              🔄 Refresh
            </button>

            {activeSheet === 'attendance' && (
              <button
                className="action-btn-secondary"
                onClick={handleDeduplicate}
                title="Consolidate duplicate records by student and date"
              >
                🧹 Deduplicate
              </button>
            )}

            <a
              href={downloadUrl}
              download={currentFileName}
              className="action-btn-primary download-link-btn"
              title="Download real .xlsx file directly"
            >
              📥 Download .xlsx
            </a>

            <button
              className="action-btn-danger"
              onClick={() => setIsClearModalOpen(true)}
              title="Clear all student registry, photos, embeddings and start fresh"
            >
              🗑️ Clear & Start Fresh
            </button>
          </div>
        </section>

        {/* Real-time KPI Summary Cards */}
        {sheetData && (
          <section className="excel-kpi-grid">
            <div className="kpi-card">
              <span className="kpi-label">File Target</span>
              <span className="kpi-value text-accent">{sheetData.file_name}</span>
              <span className="kpi-subtext">
                {sheetData.last_modified
                  ? `Modified: ${sheetData.last_modified}`
                  : 'Workbook file on disk'}
              </span>
            </div>

            {activeSheet === 'attendance' ? (
              <>
                <div className="kpi-card">
                  <span className="kpi-label">Total Records</span>
                  <span className="kpi-value">{summary.total_rows || 0}</span>
                  <span className="kpi-subtext">Unique Students: {summary.unique_students || 0}</span>
                </div>
                <div className="kpi-card">
                  <span className="kpi-label">Present</span>
                  <span className="kpi-value text-green">{summary.present_count || 0}</span>
                  <span className="kpi-subtext">Rate: {summary.rate_percent || 0}%</span>
                </div>
                <div className="kpi-card">
                  <span className="kpi-label">Absent</span>
                  <span className="kpi-value text-red">{summary.absent_count || 0}</span>
                  <span className="kpi-subtext">Dates Recorded: {summary.unique_dates || 0}</span>
                </div>
              </>
            ) : (
              <>
                <div className="kpi-card">
                  <span className="kpi-label">Enrolled Students</span>
                  <span className="kpi-value">{summary.total_students || 0}</span>
                  <span className="kpi-subtext">Active Registry</span>
                </div>
                <div className="kpi-card">
                  <span className="kpi-label">With Photos</span>
                  <span className="kpi-value text-green">{summary.with_photo || 0}</span>
                  <span className="kpi-subtext">Facial Enrolled</span>
                </div>
                <div className="kpi-card">
                  <span className="kpi-label">With ID Cards</span>
                  <span className="kpi-value text-blue">{summary.with_id_card || 0}</span>
                  <span className="kpi-subtext">Document Verified</span>
                </div>
              </>
            )}
          </section>
        )}

        {/* Filter and Search Bar */}
        <section className="excel-filter-bar">
          <div className="search-box">
            <span className="search-icon">🔍</span>
            <input
              type="text"
              placeholder="Search by ID, name, session, date, or status..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button className="clear-search-btn" onClick={() => setSearchQuery('')}>
                ×
              </button>
            )}
          </div>

          {activeSheet === 'attendance' && (
            <>
              <div className="filter-group">
                <label>Status:</label>
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="filter-select"
                >
                  <option value="ALL">All Statuses</option>
                  <option value="Present">Present Only</option>
                  <option value="Absent">Absent Only</option>
                </select>
              </div>

              {distinctDates.length > 0 && (
                <div className="filter-group">
                  <label>Date:</label>
                  <select
                    value={dateFilter}
                    onChange={(e) => setDateFilter(e.target.value)}
                    className="filter-select"
                  >
                    <option value="ALL">All Dates</option>
                    {distinctDates.map((dt) => (
                      <option key={dt} value={dt}>
                        {dt}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </>
          )}

          <div className="record-count-indicator">
            Showing <strong>{displayedRows.length}</strong> of{' '}
            <strong>{sheetData?.rows?.length || 0}</strong> records
          </div>
        </section>

        {/* Spreadsheet Data Grid */}
        <section className="excel-table-wrapper">
          {loading && !sheetData ? (
            <div className="table-loading-container">
              <LoadingSpinner size="large" />
              <p>Reading real Excel spreadsheet from disk...</p>
            </div>
          ) : error ? (
            <div className="table-error-container">
              <span className="error-icon">⚠️</span>
              <p>{error}</p>
              <button className="action-btn-secondary" onClick={() => fetchSheetData(false)}>
                Try Again
              </button>
            </div>
          ) : displayedRows.length === 0 ? (
            <div className="table-empty-container">
              <span className="empty-icon">📊</span>
              <h3>No Records in {currentFileName}</h3>
              <p>
                {searchQuery || statusFilter !== 'ALL' || dateFilter !== 'ALL'
                  ? 'No matching rows found for current filter criteria.'
                  : activeSheet === 'attendance'
                  ? 'Attendance records will appear here live when sessions start and faces are detected.'
                  : 'No students enrolled yet. Go to Live Monitor and click "+ Add Student" to register.'}
              </p>
              {searchQuery && (
                <button
                  className="action-btn-secondary"
                  onClick={() => {
                    setSearchQuery('');
                    setStatusFilter('ALL');
                    setDateFilter('ALL');
                  }}
                >
                  Clear Filters
                </button>
              )}
            </div>
          ) : (
            <table className="excel-table">
              <thead>
                <tr>
                  <th className="row-num-header">#</th>
                  {sheetData?.columns?.map((col) => {
                    const isSorted = sortField === col;
                    return (
                      <th
                        key={col}
                        onClick={() => handleSort(col)}
                        className={`sortable-header ${isSorted ? 'active-sort' : ''}`}
                        title={`Click to sort by ${col}`}
                      >
                        <div className="header-cell-content">
                          <span>{formatColumnHeader(col)}</span>
                          <span className="sort-arrow">
                            {isSorted ? (sortDirection === 'asc' ? '▲' : '▼') : '↕'}
                          </span>
                        </div>
                      </th>
                    );
                  })}
                  <th className="actions-header">Actions</th>
                </tr>
              </thead>
              <tbody>
                {displayedRows.map((row, idx) => {
                  const studentId = row.student_id;
                  const isPresent = String(row.status || '').toLowerCase() === 'present';
                  const isAbsent = String(row.status || '').toLowerCase() === 'absent';

                  return (
                    <tr
                      key={row.session_id ? `${row.session_id}-${row.student_id}-${idx}` : idx}
                      className={`excel-row ${isPresent ? 'row-present' : isAbsent ? 'row-absent' : ''}`}
                    >
                      <td className="row-num-cell">{idx + 1}</td>
                      {sheetData?.columns?.map((col) => (
                        <td key={col} className={`excel-cell col-${col}`}>
                          {renderCellValue(col, row[col], row)}
                        </td>
                      ))}
                      <td className="actions-cell">
                        {studentId && (
                          <Link
                            to={`/students/${encodeURIComponent(studentId)}`}
                            className="view-profile-btn"
                            title={`View biometric profile for student ${studentId}`}
                          >
                            Profile ↗
                          </Link>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
      </main>

      {/* Confirmation Modal for Clear & Start Fresh */}
      {isClearModalOpen && (
        <div className="modal-overlay" onClick={() => !clearLoading && setIsClearModalOpen(false)}>
          <div
            className="modal-card clear-confirm-modal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
          >
            <div className="modal-header">
              <h2>⚠️ Confirm Reset / Clear Data</h2>
              <button
                className="close-btn"
                onClick={() => !clearLoading && setIsClearModalOpen(false)}
                disabled={clearLoading}
              >
                ×
              </button>
            </div>
            <div className="modal-body">
              <p className="warning-text">
                This action will completely clear all current records so you can start clean:
              </p>
              <ul className="clear-summary-list">
                <li>🧹 All registered students in <strong>data/students.xlsx</strong></li>
                <li>📷 All reference photos in <strong>data/photos/</strong></li>
                <li>🪪 All uploaded ID cards in <strong>data/id_cards/</strong></li>
                <li>🧠 All biometric embeddings in <strong>data/embeddings.npz</strong></li>
                <li>📋 All attendance history in <strong>data/attendance.xlsx</strong></li>
              </ul>
              <p className="danger-highlight">
                Are you sure you want to proceed and start fresh from now?
              </p>
            </div>
            <div className="modal-footer">
              <button
                className="action-btn-secondary"
                onClick={() => setIsClearModalOpen(false)}
                disabled={clearLoading}
              >
                Cancel
              </button>
              <button
                className="action-btn-danger"
                onClick={handleConfirmClear}
                disabled={clearLoading}
              >
                {clearLoading ? 'Clearing System...' : 'Yes, Clear & Start Fresh'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Helper: Format column headers into human-readable titles
function formatColumnHeader(col) {
  const map = {
    session_id: 'Session ID',
    student_id: 'Student ID',
    name: 'Student Name',
    date: 'Date',
    time: 'Timestamp',
    status: 'Status',
    match_score: 'Match Score',
    photo_path: 'Reference Photo',
    id_card_path: 'ID Card Document',
  };
  return map[col] || col.replace(/_/g, ' ').toUpperCase();
}

// Helper: Format cell content based on column type
function renderCellValue(col, val, row) {
  if (val === null || val === undefined || val === '') {
    return <span className="cell-empty">—</span>;
  }

  if (col === 'status') {
    const s = String(val).trim();
    const isPres = s.toLowerCase() === 'present';
    return (
      <span className={`status-pill ${isPres ? 'pill-present' : 'pill-absent'}`}>
        {isPres ? '✓ Present' : '✗ Absent'}
      </span>
    );
  }

  if (col === 'match_score') {
    const num = parseFloat(val);
    if (isNaN(num)) return val;
    const pct = Math.round(num * 100);
    return (
      <div className="score-cell-container" title={`Similarity: ${num.toFixed(4)}`}>
        <div className="score-meter-bar">
          <div
            className={`score-meter-fill ${num >= 0.45 ? 'fill-good' : 'fill-low'}`}
            style={{ width: `${Math.min(100, pct)}%` }}
          />
        </div>
        <span className="score-text">{num.toFixed(4)}</span>
      </div>
    );
  }

  if (col === 'time') {
    return <code className="time-code">{val}</code>;
  }

  if (col === 'student_id') {
    return <strong className="student-id-text">{val}</strong>;
  }

  if (col === 'photo_path' || col === 'id_card_path') {
    const sId = row.student_id;
    if (!sId) return <span className="cell-empty">{String(val)}</span>;
    const isPhoto = col === 'photo_path';
    const targetUrl = isPhoto
      ? apiClient.getStudentPhotoUrl(sId)
      : apiClient.getStudentIdCardUrl(sId);

    return (
      <a
        href={targetUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="doc-preview-link"
        title="Open full document"
      >
        <span>{isPhoto ? '📷 Photo' : '🪪 ID Card'}</span>
      </a>
    );
  }

  return <span>{String(val)}</span>;
}

export default ExcelViewerPage;
