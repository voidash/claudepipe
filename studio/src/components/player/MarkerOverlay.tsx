import { useRef, useEffect, useCallback, type RefObject } from "react";
import type { Marker } from "../../types/edit-manifest";

interface MarkerOverlayProps {
  videoRef: RefObject<HTMLVideoElement | null>;
  markers: Marker[];
  selectedMarkerId: string | null;
  markerMode: boolean;
  currentTime: number;
  fps: number;
  onCanvasClick: (normalizedX: number, normalizedY: number) => void;
  onSelectMarker: (id: string | null) => void;
  onMoveMarker: (id: string, x: number, y: number) => void;
}

export function MarkerOverlay({
  videoRef,
  markers,
  selectedMarkerId,
  markerMode,
  currentTime,
  fps,
  onCanvasClick,
  onSelectMarker,
  onMoveMarker,
}: MarkerOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const draggingRef = useRef<string | null>(null);

  // Only show spatial markers at (or within 1 frame of) their placed time
  const frameThreshold = 1 / fps;
  const spatialMarkers = markers.filter(
    (m) => m.type === "spatial" && m.position && Math.abs(m.time - currentTime) < frameThreshold,
  );

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;
    if (!canvas || !video) return;

    const rect = video.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
    canvas.style.left = `${rect.left - (canvas.parentElement?.getBoundingClientRect().left || 0)}px`;
    canvas.style.top = `${rect.top - (canvas.parentElement?.getBoundingClientRect().top || 0)}px`;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    for (const marker of spatialMarkers) {
      if (!marker.position) continue;
      const x = marker.position.x * canvas.width;
      const y = marker.position.y * canvas.height;
      const isSelected = marker.id === selectedMarkerId;
      const radius = isSelected ? 10 : 7;

      // Crosshair
      ctx.strokeStyle = isSelected ? "#FF6B35" : "#F7C948";
      ctx.lineWidth = isSelected ? 2.5 : 1.5;

      // Circle
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.stroke();

      // Cross lines
      const crossLen = radius + 6;
      ctx.beginPath();
      ctx.moveTo(x - crossLen, y);
      ctx.lineTo(x + crossLen, y);
      ctx.moveTo(x, y - crossLen);
      ctx.lineTo(x, y + crossLen);
      ctx.stroke();

      // Label
      ctx.fillStyle = isSelected ? "#FF6B35" : "#F7C948";
      ctx.font = "11px Inter, sans-serif";
      ctx.fillText(marker.name, x + radius + 4, y - 4);
    }
  }, [spatialMarkers, selectedMarkerId, videoRef]);

  // Redraw on changes
  useEffect(() => {
    draw();
    const id = requestAnimationFrame(function loop() {
      draw();
      requestAnimationFrame(loop);
    });
    return () => cancelAnimationFrame(id);
  }, [draw]);

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      const rect = canvas.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const y = (e.clientY - rect.top) / rect.height;

      // Check if clicking on existing marker
      for (const marker of spatialMarkers) {
        if (!marker.position) continue;
        const dx = Math.abs(marker.position.x - x) * rect.width;
        const dy = Math.abs(marker.position.y - y) * rect.height;
        if (dx < 15 && dy < 15) {
          onSelectMarker(marker.id);
          return;
        }
      }

      if (markerMode) {
        onCanvasClick(x, y);
      } else {
        onSelectMarker(null);
      }
    },
    [spatialMarkers, markerMode, onCanvasClick, onSelectMarker],
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      const rect = canvas.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const y = (e.clientY - rect.top) / rect.height;

      for (const marker of spatialMarkers) {
        if (!marker.position) continue;
        const dx = Math.abs(marker.position.x - x) * rect.width;
        const dy = Math.abs(marker.position.y - y) * rect.height;
        if (dx < 15 && dy < 15) {
          draggingRef.current = marker.id;
          onSelectMarker(marker.id);
          return;
        }
      }
    },
    [spatialMarkers, onSelectMarker],
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!draggingRef.current) return;
      const canvas = canvasRef.current;
      if (!canvas) return;

      const rect = canvas.getBoundingClientRect();
      const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
      onMoveMarker(draggingRef.current, x, y);
    },
    [onMoveMarker],
  );

  const handleMouseUp = useCallback(() => {
    draggingRef.current = null;
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="absolute pointer-events-auto"
      style={{ cursor: markerMode ? "crosshair" : "default" }}
      onClick={handleClick}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    />
  );
}
