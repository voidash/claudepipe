import { useState, useCallback, useEffect } from "react";
import type { FsEntry, CameraDetection } from "../types/filesystem";

interface UseFileBrowserResult {
  currentPath: string;
  entries: FsEntry[];
  loading: boolean;
  error: string | null;
  cameraDetections: CameraDetection[];
  detectingCamera: boolean;
  navigateTo: (path: string) => void;
  navigateUp: () => void;
  refresh: () => void;
}

export function useFileBrowser(initialPath: string = "/Volumes"): UseFileBrowserResult {
  const [currentPath, setCurrentPath] = useState(initialPath);
  const [entries, setEntries] = useState<FsEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cameraDetections, setCameraDetections] = useState<CameraDetection[]>([]);
  const [detectingCamera, setDetectingCamera] = useState(false);

  const loadDirectory = useCallback(async (dirPath: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/fs/list?path=${encodeURIComponent(dirPath)}`);
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.error || "Failed to list directory");
      }
      const data = await res.json();
      setEntries(data.entries);
      setCurrentPath(data.path);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const detectCamera = useCallback(async (dirPath: string) => {
    setDetectingCamera(true);
    try {
      const res = await fetch(`/api/fs/detect-camera?path=${encodeURIComponent(dirPath)}`);
      if (res.ok) {
        const data = await res.json();
        setCameraDetections(data.detections || []);
      } else {
        setCameraDetections([]);
      }
    } catch {
      setCameraDetections([]);
    } finally {
      setDetectingCamera(false);
    }
  }, []);

  useEffect(() => {
    loadDirectory(currentPath);
    detectCamera(currentPath);
  }, [currentPath, loadDirectory, detectCamera]);

  const navigateTo = useCallback((path: string) => {
    setCurrentPath(path);
  }, []);

  const navigateUp = useCallback(() => {
    const parent = currentPath.split("/").slice(0, -1).join("/") || "/";
    setCurrentPath(parent);
  }, [currentPath]);

  const refresh = useCallback(() => {
    loadDirectory(currentPath);
    detectCamera(currentPath);
  }, [currentPath, loadDirectory, detectCamera]);

  return {
    currentPath,
    entries,
    loading,
    error,
    cameraDetections,
    detectingCamera,
    navigateTo,
    navigateUp,
    refresh,
  };
}
