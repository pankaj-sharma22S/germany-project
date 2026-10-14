import React, { useState } from 'react';

/**
 * AddStudentModal: Runtime enrollment form with client-side image preview and backend validation.
 */
export function AddStudentModal({ isOpen, onClose, onEnrollSuccess, enrollApi }) {
  const [studentId, setStudentId] = useState('');
  const [name, setName] = useState('');
  const [imageFile, setImageFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedback, setFeedback] = useState({ text: '', type: null }); // type: 'success' | 'error' | 'info'

  if (!isOpen) return null;

  function handleFileChange(e) {
    const file = e.target.files?.[0];
    if (file) {
      setImageFile(file);
      setPreviewUrl(URL.createObjectURL(file));
      setFeedback({ text: '', type: null });
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();

    const cleanId = studentId.trim();
    const cleanName = name.trim();

    if (!cleanId) {
      setFeedback({ text: 'Validation Error: Student ID is required.', type: 'error' });
      return;
    }
    if (!cleanName) {
      setFeedback({ text: 'Validation Error: Full Name is required.', type: 'error' });
      return;
    }
    if (!imageFile) {
      setFeedback({ text: 'Validation Error: Reference photo is required.', type: 'error' });
      return;
    }

    setIsSubmitting(true);
    setFeedback({ text: 'Processing photo & extracting biometric embedding...', type: 'info' });

    try {
      const res = await enrollApi(cleanId, cleanName, imageFile);
      setFeedback({
        text: res.message || `Student ${cleanName} (${cleanId}) enrolled successfully!`,
        type: 'success',
      });

      if (onEnrollSuccess) {
        onEnrollSuccess(cleanId, cleanName);
      }

      // Auto-close modal after successful enrollment
      setTimeout(() => {
        handleClose();
      }, 1500);
    } catch (err) {
      setFeedback({
        text: err.message || 'Enrollment failed. Please try again.',
        type: 'error',
      });
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleClose() {
    setStudentId('');
    setName('');
    setImageFile(null);
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      setPreviewUrl(null);
    }
    setFeedback({ text: '', type: null });
    setIsSubmitting(false);
    onClose();
  }

  return (
    <div className="modal-backdrop" data-testid="add-student-modal">
      <div className="modal-card">
        <div className="modal-header">
          <h3>Add Student (Runtime Enrollment)</h3>
          <button className="btn-close" onClick={handleClose} disabled={isSubmitting}>
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-form">
          <div className="form-group">
            <label htmlFor="student-id-input">Student ID</label>
            <input
              id="student-id-input"
              type="text"
              className="form-input"
              placeholder="e.g. S101"
              value={studentId}
              onChange={(e) => setStudentId(e.target.value)}
              disabled={isSubmitting}
              autoFocus
              data-testid="input-student-id"
            />
          </div>

          <div className="form-group">
            <label htmlFor="student-name-input">Full Name</label>
            <input
              id="student-name-input"
              type="text"
              className="form-input"
              placeholder="e.g. Rahul Sharma"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isSubmitting}
              data-testid="input-student-name"
            />
          </div>

          <div className="form-group">
            <label htmlFor="student-photo-input">Reference Photo</label>
            <div className="photo-upload-area">
              <input
                id="student-photo-input"
                type="file"
                accept="image/jpeg,image/png,image/webp,image/bmp"
                onChange={handleFileChange}
                disabled={isSubmitting}
                className="file-input"
                data-testid="input-student-photo"
              />
              <span className="upload-hint">Must contain exactly 1 clear frontal face.</span>
            </div>

            {previewUrl && (
              <div className="photo-preview-box" data-testid="photo-preview">
                <img src={previewUrl} alt="Reference Preview" className="preview-thumbnail" />
                <span className="preview-filename">{imageFile?.name}</span>
              </div>
            )}
          </div>

          {feedback.text && (
            <div className={`feedback-alert feedback-${feedback.type}`} data-testid="enroll-feedback">
              {feedback.type === 'info' && <span className="feedback-spinner" />}
              <span>{feedback.text}</span>
            </div>
          )}

          <div className="modal-footer">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleClose}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-success"
              disabled={isSubmitting}
              data-testid="btn-save-student"
            >
              {isSubmitting ? 'Saving...' : 'Save & Enroll'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
