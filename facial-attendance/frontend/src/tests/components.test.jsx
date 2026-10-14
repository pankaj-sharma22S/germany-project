import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import { FACE_STATES, FACE_STATE_CONFIG, getFaceStateConfig } from '../constants/faceStates';
import { StatusBanner } from '../components/StatusBanner';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { StabilityIndicator } from '../components/StabilityIndicator';
import { StatsPanel } from '../components/StatsPanel';
import { RecentAttendance } from '../components/RecentAttendance';
import { AddStudentModal } from '../components/AddStudentModal';
import { Controls } from '../components/Controls';
import { VideoPanel } from '../components/VideoPanel';

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

  it('renders list of confirmed items', () => {
    const items = [
      { student_id: 'S101', name: 'Rahul', time: '14:32:00', match_score: 0.74, status: 'Present' },
    ];
    render(<RecentAttendance items={items} />);
    expect(screen.getByText('S101')).toBeInTheDocument();
    expect(screen.getByText('Rahul')).toBeInTheDocument();
    expect(screen.getByText('Present')).toBeInTheDocument();
    expect(screen.getByText(/Sim: 0.74/)).toBeInTheDocument();
  });
});

describe('AddStudentModal Component', () => {
  it('validates required fields before submission', async () => {
    const mockEnroll = vi.fn();
    render(<AddStudentModal isOpen={true} onClose={() => {}} enrollApi={mockEnroll} />);

    fireEvent.click(screen.getByTestId('btn-save-student'));
    expect(await screen.findByText(/Student ID is required/i)).toBeInTheDocument();
    expect(mockEnroll).not.toHaveBeenCalled();
  });

  it('submits form and displays success message on backend confirmation', async () => {
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
      />
    );

    fireEvent.change(screen.getByTestId('input-student-id'), { target: { value: 'S999' } });
    fireEvent.change(screen.getByTestId('input-student-name'), { target: { value: 'Vikram' } });

    // Mock file input
    const file = new File(['dummy photo'], 'vikram.jpg', { type: 'image/jpeg' });
    const fileInput = screen.getByTestId('input-student-photo');
    // Mock URL.createObjectURL for preview
    global.URL.createObjectURL = vi.fn(() => 'blob:dummy-url');
    global.URL.revokeObjectURL = vi.fn();

    fireEvent.change(fileInput, { target: { files: [file] } });

    fireEvent.click(screen.getByTestId('btn-save-student'));

    await waitFor(() => {
      expect(mockEnroll).toHaveBeenCalledWith('S999', 'Vikram', file);
      expect(screen.getByText(/enrolled successfully/i)).toBeInTheDocument();
      expect(onSuccess).toHaveBeenCalledWith('S999', 'Vikram');
    });
  });

  it('displays real backend error message on enrollment rejection', async () => {
    const mockEnroll = vi.fn().mockRejectedValue(new Error('Validation Error: Multiple faces detected.'));

    render(<AddStudentModal isOpen={true} onClose={() => {}} enrollApi={mockEnroll} />);

    fireEvent.change(screen.getByTestId('input-student-id'), { target: { value: 'S111' } });
    fireEvent.change(screen.getByTestId('input-student-name'), { target: { value: 'Crowd' } });

    const file = new File(['photo'], 'crowd.jpg', { type: 'image/jpeg' });
    global.URL.createObjectURL = vi.fn(() => 'blob:url');
    fireEvent.change(screen.getByTestId('input-student-photo'), { target: { files: [file] } });

    fireEvent.click(screen.getByTestId('btn-save-student'));

    await waitFor(() => {
      expect(screen.getByText(/Multiple faces detected/i)).toBeInTheDocument();
    });
  });
});
