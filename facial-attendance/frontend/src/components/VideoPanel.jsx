import React, { useEffect, useRef } from 'react';
import { getFaceStateConfig, FACE_STATES } from '../constants/faceStates';
import { LoadingSpinner } from './LoadingSpinner';
import { StabilityIndicator } from './StabilityIndicator';

export function VideoPanel({
  frame,
  frameSize = [800, 450],
  faces = [],
  cameraActive = false,
  connected = false,
  onStartCamera,
}) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);

  // Check if any face is in verifying state
  const verifyingFace = faces.find(
    (f) => f.state === FACE_STATES.RECOGNIZING || f.state === FACE_STATES.VERIFYING
  );

  // Check if any face is stabilizing
  const stabilizingFace = faces.find(
    (f) => f.state === FACE_STATES.STABILIZING || f.state === FACE_STATES.EXCESSIVE_MOVEMENT
  );

  // Draw overlay bounding boxes
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Clear canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!cameraActive || !faces || faces.length === 0) return;

    const cw = canvas.width;
    const ch = canvas.height;

    faces.forEach((face) => {
      const [nx1, ny1, nx2, ny2] = face.normalized_box || [0, 0, 0, 0];
      const x1 = nx1 * cw;
      const y1 = ny1 * ch;
      const x2 = nx2 * cw;
      const y2 = ny2 * ch;
      const width = x2 - x1;
      const height = y2 - y1;

      const style = getFaceStateConfig(face.state);

      // Draw bounding box
      ctx.lineWidth = 3;
      ctx.strokeStyle = style.color;
      ctx.strokeRect(x1, y1, width, height);

      // Top Badge
      const topBadgeH = 24;
      const topY = Math.max(0, y1 - topBadgeH);
      ctx.fillStyle = style.badgeBg;
      ctx.fillRect(x1, topY, width, topBadgeH);

      ctx.fillStyle = style.badgeText;
      ctx.font = 'bold 12px Segoe UI, system-ui, sans-serif';
      const topText = face.name
        ? `${face.name} (${face.student_id || 'Enrolled'})`
        : style.label;
      ctx.fillText(topText, x1 + 6, topY + 16, width - 12);

      // Bottom Badge with Similarity and State Message
      const botBadgeH = 22;
      ctx.fillStyle = 'rgba(20, 20, 20, 0.85)';
      ctx.fillRect(x1, y2, width, botBadgeH);

      ctx.fillStyle = '#f0f0f0';
      ctx.font = '11px Segoe UI, system-ui, sans-serif';
      const simText = face.similarity > 0 ? `Similarity: ${face.similarity.toFixed(2)}` : '';
      const botText = simText
        ? `${simText} | ${face.message || style.description}`
        : face.message || style.description;
      ctx.fillText(botText, x1 + 6, y2 + 15, width - 12);
    });
  }, [faces, cameraActive, frameSize]);

  const [targetW, targetH] = frameSize;

  return (
    <div className="video-panel-container" ref={containerRef} data-testid="video-panel">
      <div className="video-wrapper" style={{ aspectRatio: `${targetW} / ${targetH}` }}>
        {frame && cameraActive ? (
          <img
            src={frame}
            alt="Live Camera Feed"
            className="video-feed-image"
            data-testid="video-feed"
          />
        ) : (
          <div className="camera-standby-overlay" data-testid="camera-standby">
            {!connected ? (
              <div className="standby-content">
                <div className="standby-icon">⚡</div>
                <h3>Connecting to Local Camera Stream...</h3>
                <p>Ensure backend API is running at http://127.0.0.1:8000</p>
              </div>
            ) : !cameraActive ? (
              <div className="standby-content">
                <div className="standby-icon">📷</div>
                <h3>Camera is Stopped</h3>
                <p>Click "Start Camera" to activate live facial attendance</p>
                {onStartCamera && (
                  <button className="btn btn-primary" onClick={onStartCamera}>
                    Start Camera
                  </button>
                )}
              </div>
            ) : (
              <div className="standby-content">
                <div className="standby-icon">⏳</div>
                <h3>Waiting for frames...</h3>
              </div>
            )}
          </div>
        )}

        {/* Canvas for bounding boxes synchronized with frame */}
        <canvas
          ref={canvasRef}
          width={targetW}
          height={targetH}
          className="video-overlay-canvas"
          data-testid="overlay-canvas"
        />

        {/* Real-time State Indicators overlaying the video */}
        {verifyingFace && (
          <div className="video-overlay-banner">
            <LoadingSpinner label="Face stable - verifying identity..." />
          </div>
        )}

        {stabilizingFace && !verifyingFace && (
          <div className="video-overlay-banner">
            <StabilityIndicator
              progress={stabilizingFace.stability_progress}
              message={stabilizingFace.message}
            />
          </div>
        )}
      </div>
    </div>
  );
}
