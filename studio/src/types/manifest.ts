// Types mirroring footage_manifest.json schema (manifest-schema.md)

export interface FootageManifest {
  version: string;
  project: Project;
  clips: Clip[];
  timeline: Timeline;
  units: UnitEntry[];
  sfx: SFX[];
  music: Music;
  animations: Animation[];
  thumbnails: Thumbnail[];
  outputs: Outputs;
  youtube: YouTube;
  pipeline_state: PipelineState;
  unit_info?: UnitInfo;
}

export interface Project {
  id: string;
  created: string;
  root_dir: string;
  hint: string;
  source_files: string[];
}

export interface Clip {
  id: string;
  source_path: string;
  symlink_path: string;
  type: "camera" | "screen_recording";
  classification_confidence: number;
  metadata: ClipMetadata;
  audio: ClipAudio;
  transcript: ClipTranscript;
  vad: ClipVAD;
  pitch: ClipPitch;
  scenes: ClipScenes;
  frames: ClipFrames;
  yolo: ClipYOLO;
  vision: ClipVision;
  screen_sync: ScreenSync | null;
}

export interface ClipMetadata {
  duration_seconds: number;
  width: number;
  height: number;
  fps: number;
  fps_rational: string;
  codec_video: string;
  codec_audio: string;
  audio_channels: number;
  audio_sample_rate: number;
  bit_rate_bps: number;
  creation_time: string;
  camera_model: string;
  rotation: number;
  file_size_bytes: number;
  has_audio: boolean;
}

export interface ClipAudio {
  extracted_path: string;
  denoised_path: string;
  noise_removal_applied: boolean;
  noise_removal_engine: string;
  sample_rate: number;
  duration_seconds: number;
}

export interface TranscriptSegment {
  id: string;
  start: number;
  end: number;
  text: string;
  language: string;
  confidence: number;
  words: TranscriptWord[];
}

export interface TranscriptWord {
  word: string;
  start: number;
  end: number;
  confidence: number;
}

export interface ClipTranscript {
  path: string;
  engine: string;
  segments: TranscriptSegment[];
}

export interface ClipVAD {
  path: string;
  engine: string;
  speech_segments: Array<{ start: number; end: number; confidence: number }>;
  silence_segments: Array<{ start: number; end: number; duration: number }>;
  speech_ratio: number;
}

export interface ClipPitch {
  path: string;
  mean_hz: number;
  std_hz: number;
  emphasis_points: Array<{
    time: number;
    type: "rise" | "fall" | "peak";
    magnitude: number;
    hz: number;
  }>;
}

export interface SceneBoundary {
  time: number;
  type: "cut" | "fade" | "dissolve" | "gradual";
  confidence: number;
  frame_before: string;
  frame_after: string;
}

export interface ClipScenes {
  path: string;
  boundaries: SceneBoundary[];
}

export interface ExtractedFrame {
  path: string;
  time: number;
  reason: string;
}

export interface ClipFrames {
  dir: string;
  count: number;
  extracted: ExtractedFrame[];
}

export interface YOLODetection {
  class: string;
  class_id: number;
  confidence: number;
  bbox_xyxy: number[];
  bbox_xywh: number[];
  pose?: {
    keypoints: number[][];
    facing: string;
  };
}

export interface ClipYOLO {
  path: string;
  model: string;
  detections_by_frame: Record<string, YOLODetection[]>;
  tracking_summary: {
    primary_subject_bbox_median: number[];
    subject_movement_range: {
      x_min: number;
      x_max: number;
      y_min: number;
      y_max: number;
    };
  };
}

export interface VisionAnalysis {
  frame_path: string;
  time: number;
  description: string;
  subjects: string[];
  setting: string;
  activity: string;
  quality_score: number;
  quality_issues: string[];
  text_visible: string;
  interest_score: number;
  suggested_crop_9_16: {
    x: number;
    y: number;
    w: number;
    h: number;
    reason: string;
  };
}

export interface ClipVision {
  path: string;
  analyses: VisionAnalysis[];
}

export interface ScreenSync {
  synced_to_clip: string;
  offset_seconds: number;
  correlation_score: number;
  layout: "pip" | "split" | "switch" | "side_by_side";
  layout_params: {
    pip_position?: string;
    pip_scale?: number;
    switch_timestamps?: number[];
  };
}

export interface TimelineSegment {
  id: string;
  clip_id: string;
  in_point: number;
  out_point: number;
  duration: number;
  include: boolean;
  interest_score: number;
  tags: string[];
  notes: string;
  crop_16_9: { x: number; y: number; w: number; h: number };
  crop_9_16: {
    keyframes: Array<{
      time: number;
      x: number;
      y: number;
      w: number;
      h: number;
      easing: string;
    }>;
  };
  audio_gain_db: number;
  speed_factor: number;
}

export interface TimelineTransition {
  from_segment: string;
  to_segment: string;
  type: "cut" | "crossfade" | "wipe_left" | "wipe_right" | "fade_black";
  duration_seconds: number;
}

export interface Timeline {
  segments: TimelineSegment[];
  order: string[];
  transitions: TimelineTransition[];
  total_duration_seconds: number;
}

export interface SFX {
  id: string;
  description: string;
  prompt: string;
  duration_seconds: number;
  placement: {
    type: "between_segments" | "within_segment" | "at_time";
    after_segment?: string;
    before_segment?: string;
    absolute_time?: number | null;
    time_offset_seconds: number;
  };
  generated_path: string;
  auto_confidence: "high" | "medium" | "low";
  auto_reason: string;
  approved: boolean;
  volume_db: number;
}

export interface MusicTrack {
  id: string;
  style_prompt: string;
  generated_path: string;
  duration_seconds: number;
  loop: boolean;
  ducking_keyframes: Array<{
    time: number;
    volume_db: number;
    reason?: string;
  }>;
  placement: {
    start_time: number;
    end_time: number | null;
    fade_in_seconds: number;
    fade_out_seconds: number;
  };
  approved: boolean;
}

export interface Music {
  tracks: MusicTrack[];
}

export interface Animation {
  id: string;
  type: "manim" | "remotion";
  description: string;
  source_code_path: string;
  rendered_path: string;
  duration_seconds: number;
  resolution: { w: number; h: number };
  placement: {
    type: "replace_segment" | "overlay" | "insert_after";
    target_segment: string;
    start_time: number | null;
  };
  voiceover_path: string;
  approved: boolean;
  style_config_override: Record<string, unknown>;
}

export interface Thumbnail {
  id: string;
  path: string;
  source_frame: string;
  title_text: string;
  subtitle_text: string;
  style: "bold_text_overlay" | "minimal" | "dramatic";
  resolution: { w: number; h: number };
  selected: boolean;
}

export interface OutputFormat {
  blender_path: string;
  fcpxml_path: string;
  resolution: { w: number; h: number };
  fps: number;
  render_path: string | null;
  render_status: "pending" | "rendering" | "complete" | "error";
}

export interface ShortOutput extends OutputFormat {
  id: string;
  title: string;
  segments: string[];
  duration_seconds: number;
}

export interface Outputs {
  long_16_9: OutputFormat;
  long_9_16: OutputFormat;
  shorts: ShortOutput[];
}

export interface YouTube {
  long_form: {
    title: string;
    description: string;
    tags: string[];
    category_id: number;
    default_language: string;
    default_audio_language: string;
    privacy: string;
    chapters: Array<{ time: string; title: string }>;
    cards: unknown[];
    end_screen: Record<string, unknown>;
  };
  shorts: Array<{
    short_id: string;
    title: string;
    description: string;
    tags: string[];
    visibility: string;
  }>;
}

export interface UnitEntry {
  unit_id: string;
  type: string;
  display_name: string;
  activity: string;
  clip_ids: string[];
  duration_seconds: number;
  segment_count: number;
}

export interface UnitInfo {
  unit_id: string;
  unit_type: string;
  display_name: string;
  parent_project: string;
  source_clip_id: string;
  time_range: { start: number; end: number };
  status: string;
  approved: boolean;
  notes: string;
}

export interface PipelineState {
  current_phase: number;
  completed_phases: number[];
  phase_results: Record<string, { status: string; timestamp?: string; [key: string]: unknown }>;
  errors: string[];
  warnings: string[];
  units_decomposed: boolean;
  units_decomposed_at: string | null;
  units_merged: boolean;
  units_merged_at: string | null;
  last_updated: string;
}
