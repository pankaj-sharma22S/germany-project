import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Navbar } from '../components/Navbar';
import { ExcelViewerPage } from '../pages/ExcelViewerPage';
import { apiClient } from '../api/client';

describe('Navbar Component', () => {
  it('renders brand and navigation links to Live Monitor and Interactive Excel', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Navbar connected={true} />
      </MemoryRouter>
    );

    expect(screen.getByText(/Facial Attendance System/i)).toBeInTheDocument();
    expect(screen.getByText(/Live Monitor/i)).toBeInTheDocument();
    expect(screen.getByText(/Interactive Excel/i)).toBeInTheDocument();
    expect(screen.getByText(/Connected/i)).toBeInTheDocument();
  });
});

describe('ExcelViewerPage Component', () => {
  const mockAttendanceData = {
    file_name: 'attendance.xlsx',
    exists: true,
    last_modified: '2026-10-14 22:00:00',
    file_size_bytes: 4096,
    columns: ['session_id', 'student_id', 'name', 'date', 'time', 'status', 'match_score'],
    rows: [
      {
        session_id: 'SES_01',
        student_id: '101',
        name: 'Alice Wonder',
        date: '2026-10-14',
        time: '19:34:00',
        status: 'Present',
        match_score: 0.8521,
      },
      {
        session_id: 'SES_01',
        student_id: '102',
        name: 'Bob Ross',
        date: '2026-10-14',
        time: '19:34:00',
        status: 'Absent',
        match_score: 0.0,
      },
    ],
    summary: {
      total_rows: 2,
      present_count: 1,
      absent_count: 1,
      unique_students: 2,
      unique_dates: 1,
      rate_percent: 50.0,
    },
  };

  const mockStudentsData = {
    file_name: 'students.xlsx',
    exists: true,
    last_modified: '2026-10-14 22:00:00',
    file_size_bytes: 3000,
    columns: ['student_id', 'name', 'photo_path', 'id_card_path'],
    rows: [
      {
        student_id: '101',
        name: 'Alice Wonder',
        photo_path: 'photos/101.jpg',
        id_card_path: 'id_cards/101_card.jpg',
      },
    ],
    summary: {
      total_students: 1,
      with_photo: 1,
      with_id_card: 1,
    },
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(apiClient, 'getExcelSheetData').mockImplementation((sheet) => {
      if (sheet === 'students') {
        return Promise.resolve(mockStudentsData);
      }
      return Promise.resolve(mockAttendanceData);
    });
    vi.spyOn(apiClient, 'getExcelDownloadUrl').mockReturnValue('/api/excel/download/attendance.xlsx');
  });

  it('renders spreadsheet tabs, KPI summary cards, and records table', async () => {
    render(
      <MemoryRouter initialEntries={['/excel']}>
        <ExcelViewerPage />
      </MemoryRouter>
    );

    // Check loading or data rendered
    await waitFor(() => {
      expect(screen.getByText('Alice Wonder')).toBeInTheDocument();
    });

    expect(screen.getByText('Bob Ross')).toBeInTheDocument();
    expect(screen.getByText(/✓ Present/i)).toBeInTheDocument();
    expect(screen.getByText(/✗ Absent/i)).toBeInTheDocument();
    expect(screen.getByText(/attendance.xlsx/i)).toBeInTheDocument();
  });

  it('filters rows when typing in the search box', async () => {
    render(
      <MemoryRouter initialEntries={['/excel']}>
        <ExcelViewerPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('Alice Wonder')).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText(/Search by ID, name, session/i);
    fireEvent.change(searchInput, { target: { value: 'Bob' } });

    expect(screen.queryByText('Alice Wonder')).not.toBeInTheDocument();
    expect(screen.getByText('Bob Ross')).toBeInTheDocument();
  });

  it('switches to Students Registry tab when clicked', async () => {
    render(
      <MemoryRouter initialEntries={['/excel']}>
        <ExcelViewerPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('Alice Wonder')).toBeInTheDocument();
    });

    const studentsTab = screen.getByRole('button', { name: /Students Registry/i });
    fireEvent.click(studentsTab);

    await waitFor(() => {
      expect(apiClient.getExcelSheetData).toHaveBeenCalledWith('students');
    });
  });

  it('opens clear confirmation modal when Clear & Start Fresh is clicked', async () => {
    render(
      <MemoryRouter initialEntries={['/excel']}>
        <ExcelViewerPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('Alice Wonder')).toBeInTheDocument();
    });

    const clearBtn = screen.getByRole('button', { name: /Clear & Start Fresh/i });
    fireEvent.click(clearBtn);

    expect(screen.getByText(/Confirm Reset \/ Clear Data/i)).toBeInTheDocument();
    expect(screen.getByText(/Yes, Clear & Start Fresh/i)).toBeInTheDocument();
  });
});
