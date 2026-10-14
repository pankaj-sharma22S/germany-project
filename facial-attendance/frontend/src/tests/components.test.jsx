import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { FACE_STATES, FACE_STATE_CONFIG, getFaceStateConfig } from '../constants/faceStates';
import { StatusBanner } from '../components/StatusBanner';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { StabilityIndicator } from '../components/StabilityIndicator';
import { StatsPanel } from '../components/StatsPanel';
import { RecentAttendance } from '../components/RecentAttendance';
import { AddStudentModal } from '../components/AddStudentModal';
import { ImageCard } from '../components/ImageCard';
import { StudentDetailPage } from '../pages/StudentDetailPage';
import { apiClient } from '../api/client';

describe('Face State Styles and Colors', () => {
  it('defines distinct box colors for all required states', () => {
    expect(FACE_STATE_CONFIG[FACE_STATES.UNKNOWN].color).toBe('#e74c3c');
    expect(FACE_STATE_CONFIG[FACE_STATES.CONFIRMED].color).toBe('#2ecc71');
    expect(FACE_STATE_CONFIG[FACE_STATES.EXCESSIVE_MOVEMENT].color).toBe('#e74c3c');
    expect(FACE_STATE_CONFIG[FACE_STATES.STABILIZING].color).toBe('#f39c12');
    expect(FACE_STATE_CONFIG[FACE_STATES.RECOGNIZING].color).toBe('#9b59b6');
  });

  it('getFaceStateConfig returns fallback for unknown strings', () => {
    const fallback = getFaceStateConfig('nonexistent_state');
    expect(fallback).toBeDefined();
    expect(fallback.color).toBe('#00d7ff');
  });
});

describe('StatusBanner Component', () => {
  it('renders disconnect alert when connected is false', () => {
    render(<StatusBanner connected={false} message="Some message" />);
    expect(screen.getByTestId('status-banner-disconnected')).toBeInTheDocument();
    expect(screen.getByText(/Backend Disconnected/i)).toBeInTheDocument();
  });

  it('renders movement warning message with warning tone', () => {
    render(<StatusBanner connected={true} message="Please stay still - face movement detected" />);
    const banner = screen.getByTestId('status-banner');
    expect(banner).toHaveClass('banner-warning');
    expect(screen.getByText('Please stay still - face movement detected')).toBeInTheDocument();
  });

  it('renders attendance confirmed message with success tone', () => {
    render(<StatusBanner connected={true} message="Attendance marked successfully - Rahul (S101)" />);
    const banner = screen.getByTestId('status-banner');
    expect(banner).toHaveClass('banner-success');
    expect(screen.getByText('Attendance marked successfully - Rahul (S101)')).toBeInTheDocument();
  });

  it('renders already marked message with info tone', () => {
    render(<StatusBanner connected={true} message="Already marked" />);
    const banner = screen.getByTestId('status-banner');
    expect(banner).toHaveClass('banner-info');
    expect(screen.getByText('Already marked')).toBeInTheDocument();
  });
});

describe('LoadingSpinner Component', () => {
  it('renders spinner and text when verifying', () => {
    render(<LoadingSpinner label="Face stable - verifying identity..." />);
    expect(screen.getByTestId('loading-spinner')).toBeInTheDocument();
    expect(screen.getByText('Face stable - verifying identity...')).toBeInTheDocument();
  });
});

describe('StabilityIndicator Component', () => {
  it('renders progress percentage and bar width based on backend metadata', () => {
    render(<StabilityIndicator progress={0.65} message="Stabilizing face (65%)... Stay still" />);
    expect(screen.getByText('65%')).toBeInTheDocument();
    expect(screen.getByText('Stabilizing face (65%)... Stay still')).toBeInTheDocument();
    const bar = screen.getByTestId('progress-bar-fill');
    expect(bar).toHaveStyle('width: 65%');
  });
});

describe('StatsPanel Component', () => {
  it('renders enrolled, eligible, present, remaining metrics', () => {
    const counts = { enrolled: 25, eligible: 20, present: 8, remaining: 12 };
    render(<StatsPanel counts={counts} timezone="IST" />);

    expect(screen.getByTestId('stat-enrolled')).toHaveTextContent('25');
    expect(screen.getByTestId('stat-eligible')).toHaveTextContent('20');
    expect(screen.getByTestId('stat-present')).toHaveTextContent('8');
    expect(screen.getByTestId('stat-remaining')).toHaveTextContent('12');
  });
});

describe('RecentAttendance Component', () => {
  it('renders empty state when no items', () => {
    render(<RecentAttendance items={[]} />);
    expect(screen.getByTestId('empty-attendance')).toBeInTheDocument();
  });

  it('renders list of confirmed items and View details button', () => {
    const onViewDetails = vi.fn();
    const items = [
      {
        session_id: 'SES_101',
        student_id: 'S101',
        name: 'Rahul',
        time: '14:32:00',
        match_score: 0.74,
        status: 'Present',
      },
    ];
    render(
      <MemoryRouter>
        <RecentAttendance items={items} onViewDetails={onViewDetails} />
      </MemoryRouter>
    );

    expect(screen.getByText('S101')).toBeInTheDocument();
    expect(screen.getByText('Rahul')).toBeInTheDocument();
    expect(screen.getByText('Present')).toBeInTheDocument();
    expect(screen.getByText(/Sim: 0.74/)).toBeInTheDocument();

    const viewBtn = screen.getByTestId('btn-view-details');
    expect(viewBtn).toBeInTheDocument();
    fireEvent.click(viewBtn);
    expect(onViewDetails).toHaveBeenCalledWith('S101', 'SES_101');
  });
});

describe('ImageCard Component', () => {
  it('renders placeholder when hasImage is false', () => {
    render(<ImageCard title="Student ID Card" hasImage={false} placeholderText="No ID card on file" />);
    expect(screen.getByText('Student ID Card')).toBeInTheDocument();
    expect(screen.getByText('No ID card on file')).toBeInTheDocument();
  });

  it('renders image thumbnail and opens enlarge view on click', () => {
    render(<ImageCard title="Reference Face Photo" src="/api/students/S101/photo" hasImage={true} />);
    expect(screen.getByText('Reference Face Photo')).toBeInTheDocument();

    const enlargeBtn = screen.getByText('Enlarge');
    expect(enlargeBtn).toBeInTheDocument();
    fireEvent.click(enlargeBtn);

    // Enlarged modal should be visible
    expect(screen.getByText(/Click outside or press ✕ to close/i)).toBeInTheDocument();
    const closeBtn = screen.getByRole('button', { name: /close enlarged view/i });
    fireEvent.click(closeBtn);
    expect(screen.queryByText(/Click outside or press ✕ to close/i)).not.toBeInTheDocument();
  });
});

describe('AddStudentModal Component', () => {
  beforeEach(() => {
    global.URL.createObjectURL = vi.fn(() => 'blob:dummy-url');
    global.URL.revokeObjectURL = vi.fn();
  });

  it('validates required fields including ID card when required', async () => {
    const mockEnroll = vi.fn();
    render(<AddStudentModal isOpen={true} onClose={() => {}} enrollApi={mockEnroll} idCardRequired={true} />);

    fireEvent.click(screen.getByTestId('btn-save-student'));
    expect(await screen.findByText(/Student ID is required/i)).toBeInTheDocument();

    fireEvent.change(screen.getByTestId('input-student-id'), { target: { value: 'S999' } });
    fireEvent.change(screen.getByTestId('input-student-name'), { target: { value: 'Vikram' } });
    fireEvent.change(screen.getByTestId('input-student-photo'), {
      target: { files: [new File(['photo'], 'photo.jpg', { type: 'image/jpeg' })] },
    });

    fireEvent.click(screen.getByTestId('btn-save-student'));
    expect(await screen.findByText(/ID card image is required/i)).toBeInTheDocument();
    expect(mockEnroll).not.toHaveBeenCalled();
  });

  it('submits form with both photo and ID card files', async () => {
    const mockEnroll = vi.fn().mockResolvedValue({
      success: true,
      message: 'Student Vikram (S999) enrolled successfully!',
    });
    const onSuccess = vi.fn();

    render(
      <AddStudentModal
        isOpen={true}
        onClose={() => {}}
        onEnrollSuccess={onSuccess}
        enrollApi={mockEnroll}
        idCardRequired={true}
      />
    );

    fireEvent.change(screen.getByTestId('input-student-id'), { target: { value: 'S999' } });
    fireEvent.change(screen.getByTestId('input-student-name'), { target: { value: 'Vikram' } });

    const photoFile = new File(['photo'], 'vikram.jpg', { type: 'image/jpeg' });
    const idCardFile = new File(['card'], 'card.png', { type: 'image/png' });

    fireEvent.change(screen.getByTestId('input-student-photo'), { target: { files: [photoFile] } });
    fireEvent.change(screen.getByTestId('input-student-id-card'), { target: { files: [idCardFile] } });

    fireEvent.click(screen.getByTestId('btn-save-student'));

    await waitFor(() => {
      expect(mockEnroll).toHaveBeenCalledWith('S999', 'Vikram', photoFile, idCardFile);
      expect(screen.getByText(/enrolled successfully/i)).toBeInTheDocument();
      expect(onSuccess).toHaveBeenCalledWith('S999', 'Vikram');
    });
  });
});

describe('StudentDetailPage Component', () => {
  it('renders student details, photos, and attendance record from API', async () => {
    vi.spyOn(apiClient, 'getStudentDetails').mockResolvedValue({
      student_id: 'S500',
      name: 'Priya Sharma',
      has_photo: true,
      photo_url: '/api/students/S500/photo',
      has_id_card: true,
      id_card_url: '/api/students/S500/id-card',
      attendance: {
        session_id: 'SES_TEST_01',
        status: 'Present',
        date: '2026-10-14',
        time: '11:15:00',
        similarity: 0.8542,
      },
    });

    render(
      <MemoryRouter initialEntries={['/students/S500?session=SES_TEST_01']}>
        <Routes>
          <Route path="/students/:studentId" element={<StudentDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByTestId('detail-page-loading')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId('student-detail-page')).toBeInTheDocument();
      expect(screen.getByTestId('student-id-val')).toHaveTextContent('S500');
      expect(screen.getByTestId('student-name-val')).toHaveTextContent('Priya Sharma');
      expect(screen.getByText('Present')).toBeInTheDocument();
      expect(screen.getByText('0.8542')).toBeInTheDocument();
      expect(screen.getByText('Reference Face Photo')).toBeInTheDocument();
      expect(screen.getByText('Student ID Card')).toBeInTheDocument();
      expect(screen.getByTestId('link-back-live')).toBeInTheDocument();
    });
  });

  it('renders error state when student is not found (404)', async () => {
    vi.spyOn(apiClient, 'getStudentDetails').mockRejectedValue(new Error("Student 'UNKNOWN' not found."));

    render(
      <MemoryRouter initialEntries={['/students/UNKNOWN']}>
        <Routes>
          <Route path="/students/:studentId" element={<StudentDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId('detail-page-error')).toBeInTheDocument();
      expect(screen.getByText(/Student Not Found/i)).toBeInTheDocument();
      expect(screen.getByTestId('btn-back-home')).toBeInTheDocument();
    });
  });

  it('renders "Not marked in this session" when attendance is absent', async () => {
    vi.spyOn(apiClient, 'getStudentDetails').mockResolvedValue({
      student_id: 'S501',
      name: 'Unmarked Student',
      has_photo: true,
      has_id_card: false,
      attendance: {
        session_id: 'SES_TEST_02',
        status: 'Not marked in this session',
      },
    });

    render(
      <MemoryRouter initialEntries={['/students/S501?session=SES_TEST_02']}>
        <Routes>
          <Route path="/students/:studentId" element={<StudentDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId('status-not-marked')).toBeInTheDocument();
      expect(screen.getByText('Not marked in this session')).toBeInTheDocument();
      expect(screen.getAllByText('No ID card on file').length).toBeGreaterThanOrEqual(1);
    });
  });
});
