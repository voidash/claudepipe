import { useCallback } from "react";
import {
  Folder,
  File,
  ChevronRight,
  ArrowUp,
  RefreshCw,
  HardDrive,
  Video,
  Music,
  Image,
  FileText,
} from "lucide-react";
import type { FsEntry } from "../../types/filesystem";
import { cn } from "../../lib/cn";

function formatSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i > 1 ? 1 : 0)} ${units[i]}`;
}

function fileIcon(ext: string) {
  const lower = ext.toLowerCase();
  if ([".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".insv"].includes(lower)) return Video;
  if ([".wav", ".mp3", ".aac", ".flac", ".ogg", ".m4a"].includes(lower)) return Music;
  if ([".jpg", ".jpeg", ".png", ".webp", ".gif", ".cr2", ".arw", ".dng", ".heic"].includes(lower)) return Image;
  if ([".txt", ".md", ".srt", ".vtt", ".json"].includes(lower)) return FileText;
  return File;
}

interface FileBrowserProps {
  currentPath: string;
  entries: FsEntry[];
  loading: boolean;
  error: string | null;
  selectedPaths: Set<string>;
  onNavigate: (path: string) => void;
  onNavigateUp: () => void;
  onRefresh: () => void;
  onSelectFile: (entry: FsEntry) => void;
  onSelectAll: (entries: FsEntry[]) => void;
}

export function FileBrowser({
  currentPath,
  entries,
  loading,
  error,
  selectedPaths,
  onNavigate,
  onNavigateUp,
  onRefresh,
  onSelectFile,
  onSelectAll,
}: FileBrowserProps) {
  const pathParts = currentPath.split("/").filter(Boolean);
  const files = entries.filter((e) => e.type === "file");

  const handlePathClick = useCallback(
    (index: number) => {
      const path = "/" + pathParts.slice(0, index + 1).join("/");
      onNavigate(path);
    },
    [pathParts, onNavigate],
  );

  return (
    <div className="flex flex-col h-full border border-cp-border rounded-lg overflow-hidden bg-cp-bg">
      {/* Breadcrumb + controls */}
      <div className="flex items-center gap-1 px-3 py-2 border-b border-cp-border bg-cp-bg-elevated">
        <button
          onClick={onNavigateUp}
          className="p-1 hover:bg-cp-bg-surface rounded transition-colors"
          title="Go up"
        >
          <ArrowUp className="w-4 h-4" />
        </button>

        <button
          onClick={() => onNavigate("/Volumes")}
          className="p-1 hover:bg-cp-bg-surface rounded transition-colors"
          title="Volumes"
        >
          <HardDrive className="w-4 h-4" />
        </button>

        <div className="flex items-center gap-0.5 flex-1 min-w-0 ml-2 overflow-x-auto">
          <button
            onClick={() => onNavigate("/")}
            className="text-xs text-cp-text-muted hover:text-cp-text px-1"
          >
            /
          </button>
          {pathParts.map((part, i) => (
            <div key={i} className="flex items-center shrink-0">
              <ChevronRight className="w-3 h-3 text-cp-text-muted" />
              <button
                onClick={() => handlePathClick(i)}
                className={cn(
                  "text-xs px-1 rounded hover:bg-cp-bg-surface",
                  i === pathParts.length - 1 ? "text-cp-text font-medium" : "text-cp-text-muted",
                )}
              >
                {part}
              </button>
            </div>
          ))}
        </div>

        <button
          onClick={onRefresh}
          className="p-1 hover:bg-cp-bg-surface rounded transition-colors ml-1"
          title="Refresh"
        >
          <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} />
        </button>

        {files.length > 0 && (
          <button
            onClick={() => onSelectAll(files)}
            className="text-xs px-2 py-0.5 rounded hover:bg-cp-bg-surface text-cp-text-muted"
          >
            Select all files
          </button>
        )}
      </div>

      {/* Path input */}
      <div className="px-3 py-1.5 border-b border-cp-border">
        <input
          type="text"
          value={currentPath}
          onChange={(e) => onNavigate(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onNavigate((e.target as HTMLInputElement).value);
          }}
          className="w-full bg-cp-bg-surface border border-cp-border rounded px-2 py-1 text-xs font-code focus:border-cp-primary outline-none"
          placeholder="/path/to/footage"
        />
      </div>

      {/* File listing */}
      <div className="flex-1 overflow-y-auto">
        {error && (
          <div className="p-4 text-sm text-cp-error text-center">{error}</div>
        )}

        {loading && entries.length === 0 && (
          <div className="p-4 text-sm text-cp-text-muted text-center">Loading...</div>
        )}

        {!loading && !error && entries.length === 0 && (
          <div className="p-4 text-sm text-cp-text-muted text-center">Empty directory</div>
        )}

        {entries.map((entry) => {
          const isDir = entry.type === "directory";
          const isSelected = selectedPaths.has(entry.path);
          const Icon = isDir ? Folder : fileIcon(entry.extension);

          return (
            <div
              key={entry.path}
              className={cn(
                "flex items-center gap-2 px-3 py-1.5 cursor-pointer transition-colors text-sm",
                "hover:bg-cp-bg-surface",
                isSelected && "bg-cp-primary/10 border-l-2 border-cp-primary",
              )}
              onClick={() => {
                if (isDir) {
                  onNavigate(entry.path);
                } else {
                  onSelectFile(entry);
                }
              }}
              onDoubleClick={() => {
                if (isDir) onNavigate(entry.path);
              }}
            >
              <Icon
                className={cn(
                  "w-4 h-4 shrink-0",
                  isDir ? "text-cp-accent" : "text-cp-text-secondary",
                )}
              />
              <span className="flex-1 truncate">{entry.name}</span>
              {!isDir && (
                <span className="text-xs text-cp-text-muted shrink-0">
                  {formatSize(entry.size)}
                </span>
              )}
              {isDir && (
                <ChevronRight className="w-3.5 h-3.5 text-cp-text-muted shrink-0" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
