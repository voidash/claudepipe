import { Camera, CheckCircle } from "lucide-react";
import type { CameraDetection as CameraDetectionType } from "../../types/filesystem";

function formatSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i > 1 ? 1 : 0)} ${units[i]}`;
}

interface CameraDetectionProps {
  detections: CameraDetectionType[];
  onAddAll: (detection: CameraDetectionType) => void;
}

export function CameraDetectionBanner({ detections, onAddAll }: CameraDetectionProps) {
  if (detections.length === 0) return null;

  return (
    <div className="space-y-2">
      {detections.map((det, i) => (
        <div
          key={i}
          className="flex items-center gap-3 px-4 py-3 bg-cp-secondary/10 border border-cp-secondary/30 rounded-lg"
        >
          <Camera className="w-5 h-5 text-cp-secondary shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium">
              {det.label}
            </div>
            <div className="text-xs text-cp-text-muted">
              {det.total_count} files · {formatSize(det.total_size_bytes)}
            </div>
          </div>
          <button
            onClick={() => onAddAll(det)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-cp-secondary hover:bg-cp-secondary-hover transition-colors"
          >
            <CheckCircle className="w-3.5 h-3.5" />
            Add all
          </button>
        </div>
      ))}
    </div>
  );
}
