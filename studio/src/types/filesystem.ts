export interface FsEntry {
  name: string;
  path: string;
  type: "file" | "directory" | "symlink";
  size: number;
  modified: string;
  extension: string;
  // Media metadata (only for probed files)
  media?: MediaProbe;
}

export interface MediaProbe {
  duration_seconds: number;
  width: number;
  height: number;
  fps: number;
  codec_video: string;
  codec_audio: string;
  has_audio: boolean;
  camera_model: string;
  creation_time: string;
}

export interface CameraDetection {
  camera_type: "gopro" | "insta360" | "pixel" | "canon" | "generic";
  label: string;
  files: CameraFile[];
  total_count: number;
  total_size_bytes: number;
  total_duration_seconds: number;
}

export interface CameraFile {
  path: string;
  name: string;
  size: number;
  extension: string;
  // Quick metadata from filename patterns, not full probe
  chapter?: number;
}

export interface SelectedFile {
  path: string;
  name: string;
  size: number;
  extension: string;
  type: "video" | "audio" | "image" | "text" | "other";
  important: boolean;
  media?: MediaProbe;
  probing?: boolean;
}

export interface ProjectCreateRequest {
  project_dir: string;
  hint: string;
  files: Array<{
    path: string;
    important: boolean;
  }>;
}

export interface ProjectCreateResponse {
  ok: boolean;
  project_root: string;
  manifest_path: string;
  file_count: number;
}

export function classifyFileType(ext: string): SelectedFile["type"] {
  const lower = ext.toLowerCase();
  if ([".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".insv", ".insp", ".lrv"].includes(lower)) return "video";
  if ([".wav", ".mp3", ".aac", ".flac", ".ogg", ".m4a"].includes(lower)) return "audio";
  if ([".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".cr2", ".arw", ".dng", ".nef", ".heic"].includes(lower)) return "image";
  if ([".txt", ".md", ".srt", ".vtt", ".json"].includes(lower)) return "text";
  return "other";
}
