import { X, Star, Video, Music, Image, FileText, File, Loader2 } from "lucide-react";
import type { SelectedFile } from "../../types/filesystem";
import { cn } from "../../lib/cn";

function formatSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i > 1 ? 1 : 0)} ${units[i]}`;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

const typeIcons: Record<string, typeof Video> = {
  video: Video,
  audio: Music,
  image: Image,
  text: FileText,
  other: File,
};

interface SelectedFilesProps {
  files: SelectedFile[];
  onRemove: (path: string) => void;
  onToggleImportant: (path: string) => void;
  onClear: () => void;
}

export function SelectedFiles({ files, onRemove, onToggleImportant, onClear }: SelectedFilesProps) {
  const totalSize = files.reduce((s, f) => s + f.size, 0);
  const importantCount = files.filter((f) => f.important).length;
  const videoCount = files.filter((f) => f.type === "video").length;
  const totalDuration = files.reduce((s, f) => s + (f.media?.duration_seconds || 0), 0);

  return (
    <div className="flex flex-col h-full">
      {/* Header with stats */}
      <div className="px-3 py-2 border-b border-cp-border bg-cp-bg-elevated flex items-center justify-between">
        <div>
          <h3 className="text-sm font-heading font-semibold">Selected Files</h3>
          <div className="text-xs text-cp-text-muted mt-0.5">
            {files.length} files · {formatSize(totalSize)}
            {videoCount > 0 && totalDuration > 0 && ` · ${formatDuration(totalDuration)} total`}
            {importantCount > 0 && (
              <span className="text-cp-accent"> · {importantCount} important</span>
            )}
          </div>
        </div>
        {files.length > 0 && (
          <button
            onClick={onClear}
            className="text-xs text-cp-text-muted hover:text-cp-error px-2 py-0.5 rounded hover:bg-cp-bg-surface"
          >
            Clear all
          </button>
        )}
      </div>

      {/* File list */}
      <div className="flex-1 overflow-y-auto">
        {files.length === 0 && (
          <div className="p-6 text-center text-cp-text-muted text-sm">
            <p>No files selected</p>
            <p className="text-xs mt-1">Browse or drag files here</p>
          </div>
        )}

        {files.map((file) => {
          const Icon = typeIcons[file.type] || File;
          return (
            <div
              key={file.path}
              className="flex items-center gap-2 px-3 py-2 border-b border-cp-border/50 hover:bg-cp-bg-surface group"
            >
              <Icon className="w-4 h-4 text-cp-text-secondary shrink-0" />

              <div className="flex-1 min-w-0">
                <div className="text-sm truncate">{file.name}</div>
                <div className="text-xs text-cp-text-muted flex items-center gap-2">
                  <span>{formatSize(file.size)}</span>
                  {file.probing && (
                    <span className="flex items-center gap-1">
                      <Loader2 className="w-3 h-3 animate-spin" /> probing...
                    </span>
                  )}
                  {file.media && (
                    <>
                      {file.media.width > 0 && (
                        <span>
                          {file.media.width}x{file.media.height}
                        </span>
                      )}
                      {file.media.duration_seconds > 0 && (
                        <span>{formatDuration(file.media.duration_seconds)}</span>
                      )}
                      {file.media.camera_model && (
                        <span className="text-cp-secondary">{file.media.camera_model}</span>
                      )}
                    </>
                  )}
                </div>
              </div>

              {/* Important toggle */}
              <button
                onClick={() => onToggleImportant(file.path)}
                className={cn(
                  "p-1 rounded transition-colors",
                  file.important
                    ? "text-cp-accent"
                    : "text-cp-text-muted opacity-0 group-hover:opacity-100 hover:text-cp-accent",
                )}
                title={file.important ? "Marked important — won't be auto-excluded" : "Mark as important"}
              >
                <Star className={cn("w-4 h-4", file.important && "fill-cp-accent")} />
              </button>

              {/* Remove */}
              <button
                onClick={() => onRemove(file.path)}
                className="p-1 rounded text-cp-text-muted opacity-0 group-hover:opacity-100 hover:text-cp-error transition-colors"
                title="Remove"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
