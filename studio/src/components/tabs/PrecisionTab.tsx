import { useRef, useEffect, useCallback, useState } from "react";
import { TransformWrapper, TransformComponent } from "react-zoom-pan-pinch";
import { ZoomIn, ZoomOut, Maximize, RefreshCw } from "lucide-react";
import type { Marker } from "../../types/edit-manifest";
import type { VideoPlayerHandle } from "../player/VideoPlayer";

interface PrecisionTabProps {
  playerRef: React.RefObject<VideoPlayerHandle | null>;
  isActive: boolean;
  markers: Marker[];
  markerMode: boolean;
  selectedMarkerId: string | null;
  onAddSpatialMarker: (time: number, frame: number, x: number, y: number, clipId: string) => void;
  onSelectMarker: (id: string | null) => void;
  onMoveMarker: (id: string, x: number, y: number) => void;
  activeClipId: string;
}

export function PrecisionTab({
  playerRef,
  isActive,
  markers,
  markerMode,
  selectedMarkerId,
  onAddSpatialMarker,
  onSelectMarker,
  onMoveMarker,
  activeClipId,
}: PrecisionTabProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [zoom, setZoom] = useState(1);
  const [captureTime, setCaptureTime] = useState(0);
  const [captureFrame, setCaptureFrame] = useState(0);
  const [hasFrame, setHasFrame] = useState(false);

  const captureCurrentFrame = useCallback(() => {
    const canvas = canvasRef.current;
    const video = playerRef.current?.getVideoElement();
    if (!canvas || !video || !video.videoWidth) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    setCaptureTime(playerRef.current?.getCurrentTime() ?? 0);
    setCaptureFrame(playerRef.current?.getCurrentFrame() ?? 0);
    setHasFrame(true);
  }, [playerRef]);

  // Draw markers on canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !hasFrame) return;

    const video = playerRef.current?.getVideoElement();
    if (!video || !video.videoWidth) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // Redraw video frame first
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    // Draw markers
    const spatialMarkers = markers.filter((m) => m.type === "spatial" && m.position);
    for (const marker of spatialMarkers) {
      if (!marker.position) continue;
      const x = marker.position.x * canvas.width;
      const y = marker.position.y * canvas.height;
      const isSelected = marker.id === selectedMarkerId;

      ctx.strokeStyle = isSelected ? "#FF6B35" : "#F7C948";
      ctx.lineWidth = isSelected ? 3 : 2;

      ctx.beginPath();
      ctx.arc(x, y, isSelected ? 12 : 8, 0, Math.PI * 2);
      ctx.stroke();

      const crossLen = 18;
      ctx.beginPath();
      ctx.moveTo(x - crossLen, y);
      ctx.lineTo(x + crossLen, y);
      ctx.moveTo(x, y - crossLen);
      ctx.lineTo(x, y + crossLen);
      ctx.stroke();

      ctx.fillStyle = isSelected ? "#FF6B35" : "#F7C948";
      ctx.font = "bold 14px Inter, sans-serif";
      ctx.fillText(marker.name, x + 16, y - 8);
    }
  }, [markers, selectedMarkerId, hasFrame, playerRef]);

  // Capture frame when tab becomes active
  useEffect(() => {
    if (isActive) captureCurrentFrame();
  }, [isActive, captureCurrentFrame]);

  const handleCanvasClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      const x = ((e.clientX - rect.left) * scaleX) / canvas.width;
      const y = ((e.clientY - rect.top) * scaleY) / canvas.height;

      // Check existing markers
      const spatialMarkers = markers.filter((m) => m.type === "spatial" && m.position);
      for (const marker of spatialMarkers) {
        if (!marker.position) continue;
        const dx = Math.abs(marker.position.x - x) * canvas.width;
        const dy = Math.abs(marker.position.y - y) * canvas.height;
        if (dx < 20 && dy < 20) {
          onSelectMarker(marker.id);
          return;
        }
      }

      if (markerMode && activeClipId) {
        onAddSpatialMarker(captureTime, captureFrame, x, y, activeClipId);
      } else {
        onSelectMarker(null);
      }
    },
    [markers, markerMode, activeClipId, captureTime, captureFrame, onAddSpatialMarker, onSelectMarker],
  );

  if (!hasFrame) {
    const video = playerRef.current?.getVideoElement();
    return (
      <div className="h-full flex flex-col items-center justify-center text-cp-text-muted text-sm gap-2">
        <p>{video ? "Click refresh to capture the current frame" : "Play a video first to use precision view"}</p>
        {video && (
          <button
            onClick={captureCurrentFrame}
            className="flex items-center gap-1 px-3 py-1 text-xs rounded bg-cp-bg-surface border border-cp-border hover:border-cp-primary"
          >
            <RefreshCw className="w-3 h-3" />
            Capture frame
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-cp-border bg-cp-bg-elevated">
        <button
          onClick={captureCurrentFrame}
          className="flex items-center gap-1 px-2 py-0.5 text-xs rounded hover:bg-cp-bg-surface border border-cp-border"
          title="Capture current frame"
        >
          <RefreshCw className="w-3 h-3" />
          Refresh
        </button>
        <span className="text-xs text-cp-text-muted">
          F{captureFrame}
        </span>
        <span className="text-xs text-cp-text-secondary">Zoom: {zoom.toFixed(1)}x</span>
        <input
          type="range"
          min="1"
          max="10"
          step="0.1"
          value={zoom}
          onChange={(e) => setZoom(parseFloat(e.target.value))}
          className="w-24 accent-cp-primary"
        />
        {markerMode && (
          <span className="text-xs text-cp-accent ml-auto">MARKER MODE</span>
        )}
      </div>

      <div className="flex-1 overflow-hidden bg-black">
        <TransformWrapper
          initialScale={zoom}
          minScale={1}
          maxScale={10}
          onTransformed={(_, state) => setZoom(state.scale)}
        >
          {({ zoomIn, zoomOut, resetTransform }) => (
            <>
              <div className="absolute top-2 right-2 z-10 flex gap-1">
                <button
                  onClick={() => zoomIn()}
                  className="p-1 bg-cp-bg-elevated/80 rounded hover:bg-cp-bg-surface"
                >
                  <ZoomIn className="w-4 h-4" />
                </button>
                <button
                  onClick={() => zoomOut()}
                  className="p-1 bg-cp-bg-elevated/80 rounded hover:bg-cp-bg-surface"
                >
                  <ZoomOut className="w-4 h-4" />
                </button>
                <button
                  onClick={() => resetTransform()}
                  className="p-1 bg-cp-bg-elevated/80 rounded hover:bg-cp-bg-surface"
                >
                  <Maximize className="w-4 h-4" />
                </button>
              </div>
              <TransformComponent
                wrapperStyle={{ width: "100%", height: "100%" }}
                contentStyle={{ width: "100%", height: "100%" }}
              >
                <canvas
                  ref={canvasRef}
                  className="max-w-full max-h-full mx-auto cursor-crosshair"
                  onClick={handleCanvasClick}
                />
              </TransformComponent>
            </>
          )}
        </TransformWrapper>
      </div>
    </div>
  );
}
