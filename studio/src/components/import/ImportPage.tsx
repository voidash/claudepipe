import { useState, useCallback } from "react";
import { Rocket, AlertCircle } from "lucide-react";
import { useFileBrowser } from "../../hooks/useFileBrowser";
import { FileBrowser } from "./FileBrowser";
import { SelectedFiles } from "./SelectedFiles";
import { CameraDetectionBanner } from "./CameraDetection";
import { DropZone } from "./DropZone";
import type { FsEntry, SelectedFile, CameraDetection } from "../../types/filesystem";
import { classifyFileType } from "../../types/filesystem";
import { cn } from "../../lib/cn";

interface ImportPageProps {
  defaultProjectDir: string;
  onProjectCreated: (projectRoot: string) => void;
}

export function ImportPage({ defaultProjectDir, onProjectCreated }: ImportPageProps) {
  const browser = useFileBrowser("/Volumes");
  const [selectedFiles, setSelectedFiles] = useState<SelectedFile[]>([]);
  const [hint, setHint] = useState("");
  const [projectDir, setProjectDir] = useState(defaultProjectDir);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedPaths = new Set(selectedFiles.map((f) => f.path));

  // Add a file and probe it for metadata
  const addFile = useCallback(
    (path: string, name: string, size: number, extension: string) => {
      if (selectedFiles.some((f) => f.path === path)) return;

      const fileType = classifyFileType(extension);
      const newFile: SelectedFile = {
        path,
        name,
        size,
        extension,
        type: fileType,
        important: false,
        probing: fileType === "video" || fileType === "audio",
      };

      setSelectedFiles((prev) => [...prev, newFile]);

      // Probe media files for metadata
      if (newFile.probing) {
        fetch(`/api/fs/probe?path=${encodeURIComponent(path)}`)
          .then((res) => (res.ok ? res.json() : null))
          .then((media) => {
            setSelectedFiles((prev) =>
              prev.map((f) =>
                f.path === path ? { ...f, media: media || undefined, probing: false } : f,
              ),
            );
          })
          .catch(() => {
            setSelectedFiles((prev) =>
              prev.map((f) => (f.path === path ? { ...f, probing: false } : f)),
            );
          });
      }
    },
    [selectedFiles],
  );

  const handleSelectFile = useCallback(
    (entry: FsEntry) => {
      if (selectedPaths.has(entry.path)) {
        // Deselect
        setSelectedFiles((prev) => prev.filter((f) => f.path !== entry.path));
      } else {
        addFile(entry.path, entry.name, entry.size, entry.extension);
      }
    },
    [selectedPaths, addFile],
  );

  const handleSelectAll = useCallback(
    (entries: FsEntry[]) => {
      for (const entry of entries) {
        if (!selectedPaths.has(entry.path)) {
          addFile(entry.path, entry.name, entry.size, entry.extension);
        }
      }
    },
    [selectedPaths, addFile],
  );

  const handleCameraAddAll = useCallback(
    (detection: CameraDetection) => {
      for (const file of detection.files) {
        if (!selectedPaths.has(file.path)) {
          addFile(file.path, file.name, file.size, file.extension);
        }
      }
    },
    [selectedPaths, addFile],
  );

  const handleRemoveFile = useCallback((path: string) => {
    setSelectedFiles((prev) => prev.filter((f) => f.path !== path));
  }, []);

  const handleToggleImportant = useCallback((path: string) => {
    setSelectedFiles((prev) =>
      prev.map((f) => (f.path === path ? { ...f, important: !f.important } : f)),
    );
  }, []);

  const handleClearAll = useCallback(() => {
    setSelectedFiles([]);
  }, []);

  const handleDropPaths = useCallback(
    (paths: string[]) => {
      // For browser-native drops, the paths are just filenames (no full path)
      // The user should use the file browser for actual file selection
      // But we can still show what was dropped
      for (const p of paths) {
        // If it looks like an absolute path, try to add it
        if (p.startsWith("/")) {
          const name = p.split("/").pop() || p;
          const ext = "." + name.split(".").pop();
          addFile(p, name, 0, ext);
        }
      }
    },
    [addFile],
  );

  const handleStartPipeline = useCallback(async () => {
    if (selectedFiles.length === 0) return;

    setCreating(true);
    setError(null);

    try {
      const res = await fetch("/api/project/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_dir: projectDir,
          hint,
          files: selectedFiles.map((f) => ({
            path: f.path,
            important: f.important,
          })),
        }),
      });

      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.error || "Failed to create project");
      }

      const data = await res.json();
      onProjectCreated(data.project_root);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create project");
    } finally {
      setCreating(false);
    }
  }, [selectedFiles, projectDir, hint, onProjectCreated]);

  return (
    <div className="h-screen flex flex-col bg-cp-bg">
      {/* Header */}
      <div className="h-12 flex items-center justify-between px-6 border-b border-cp-border bg-cp-bg-elevated shrink-0">
        <div>
          <h1 className="text-sm font-heading font-bold">
            <span className="text-cp-primary">claudepipe</span>{" "}
            <span className="text-cp-text-secondary">import</span>
          </h1>
        </div>
      </div>

      <div className="flex-1 flex min-h-0">
        {/* Left: File browser */}
        <div className="flex-1 flex flex-col p-4 gap-3 min-w-0">
          {/* Camera detection banner */}
          <CameraDetectionBanner
            detections={browser.cameraDetections}
            onAddAll={handleCameraAddAll}
          />

          {/* File browser */}
          <div className="flex-1 min-h-0">
            <FileBrowser
              currentPath={browser.currentPath}
              entries={browser.entries}
              loading={browser.loading}
              error={browser.error}
              selectedPaths={selectedPaths}
              onNavigate={browser.navigateTo}
              onNavigateUp={browser.navigateUp}
              onRefresh={browser.refresh}
              onSelectFile={handleSelectFile}
              onSelectAll={handleSelectAll}
            />
          </div>

          {/* Drop zone */}
          <DropZone onDropPaths={handleDropPaths} />
        </div>

        {/* Right: Selected files + project setup */}
        <div className="w-[380px] flex flex-col border-l border-cp-border">
          {/* Selected files list */}
          <div className="flex-1 min-h-0">
            <SelectedFiles
              files={selectedFiles}
              onRemove={handleRemoveFile}
              onToggleImportant={handleToggleImportant}
              onClear={handleClearAll}
            />
          </div>

          {/* Project setup */}
          <div className="border-t border-cp-border p-4 space-y-3 bg-cp-bg-elevated">
            <div>
              <label className="block text-xs text-cp-text-secondary mb-1 font-medium">
                What is this video about?
              </label>
              <textarea
                value={hint}
                onChange={(e) => setHint(e.target.value)}
                className="w-full bg-cp-bg border border-cp-border rounded px-3 py-2 text-sm focus:border-cp-primary outline-none resize-none"
                rows={3}
                placeholder="e.g. Starting my content creation journey — setup, first recordings, tips for beginners"
              />
            </div>

            <div>
              <label className="block text-xs text-cp-text-secondary mb-1 font-medium">
                Project location
              </label>
              <input
                type="text"
                value={projectDir}
                onChange={(e) => setProjectDir(e.target.value)}
                className="w-full bg-cp-bg border border-cp-border rounded px-3 py-1.5 text-sm font-code focus:border-cp-primary outline-none"
              />
            </div>

            {error && (
              <div className="flex items-center gap-2 text-xs text-cp-error">
                <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                {error}
              </div>
            )}

            <button
              onClick={handleStartPipeline}
              disabled={selectedFiles.length === 0 || creating || !hint.trim()}
              className={cn(
                "w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded font-medium text-sm transition-colors",
                selectedFiles.length > 0 && hint.trim()
                  ? "bg-cp-primary hover:bg-cp-primary-hover"
                  : "bg-cp-bg-surface text-cp-text-muted cursor-not-allowed",
              )}
            >
              <Rocket className="w-4 h-4" />
              {creating ? "Creating project..." : `Start Pipeline (${selectedFiles.length} files)`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
