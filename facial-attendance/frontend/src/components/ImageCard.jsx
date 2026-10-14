import React, { useState } from 'react';

/**
 * ImageCard Component:
 * Displays an image (Reference Photo or ID Card) with:
 * - Loading spinner
 * - Placeholder when image is missing / not on file
 * - Error fallback state when image fails to load
 * - Click to enlarge modal for high-detail reading (essential for ID card text)
 */
export function ImageCard({ title, src, alt, placeholderText = 'No image on file', hasImage = true }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [enlarged, setEnlarged] = useState(false);

  const handleImageLoad = () => {
    setLoading(false);
    setError(false);
  };

  const handleImageError = () => {
    setLoading(false);
    setError(true);
  };

  return (
    <>
      <div className="image-card">
        <div className="image-card-header">
          <span className="image-card-title">{title}</span>
          {hasImage && !error && (
            <button
              type="button"
              className="btn-enlarge"
              onClick={() => setEnlarged(true)}
              title="Click to enlarge"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
              </svg>
              Enlarge
            </button>
          )}
        </div>

        <div className="image-card-body" onClick={() => hasImage && !error && setEnlarged(true)}>
          {!hasImage ? (
            <div className="image-placeholder">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                <circle cx="8.5" cy="8.5" r="1.5" />
                <polyline points="21 15 16 10 5 21" />
              </svg>
              <p>{placeholderText}</p>
            </div>
          ) : error ? (
            <div className="image-error">
              <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#e74c3c" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              <p>Failed to load image</p>
            </div>
          ) : (
            <>
              {loading && (
                <div className="image-loading">
                  <div className="spinner-small" />
                  <span>Loading...</span>
                </div>
              )}
              <img
                src={src}
                alt={alt || title}
                className={`image-preview-thumb ${loading ? 'hidden' : ''}`}
                onLoad={handleImageLoad}
                onError={handleImageError}
              />
            </>
          )}
        </div>
      </div>

      {/* Enlarged Modal Lightbox */}
      {enlarged && (
        <div className="modal-backdrop" onClick={() => setEnlarged(false)}>
          <div className="image-modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="image-modal-header">
              <h3>{title}</h3>
              <button
                type="button"
                className="btn-modal-close"
                onClick={() => setEnlarged(false)}
                aria-label="Close enlarged view"
              >
                ✕
              </button>
            </div>
            <div className="image-modal-body">
              <img src={src} alt={alt || title} className="image-enlarged-view" />
            </div>
            <div className="image-modal-footer">
              <span className="image-modal-hint">Click outside or press ✕ to close</span>
              <button type="button" className="btn-secondary" onClick={() => setEnlarged(false)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
