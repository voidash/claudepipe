import { useRef, useState, useCallback, useEffect, useMemo, forwardRef, useImperativeHandle } from "react";
import {
  Play,
  Pause,
  ChevronLeft,
  ChevronRight,
  Scissors,
} from "lucide-react";
import type { Clip } from "../../types/manifest";
import type { Marker, ClipEdit, WordCut } from "../../types/edit-manifest";
import { formatFrameTimecode, timeToFrame } from "../../lib/frame-utils";
import { mediaUrl } from "../../api/client";
import {
  computePlaybackRanges,
  findContainingSkipRange,
  clampToPlayable,
  hasPlayableContent,
  type PlaybackConstraints,
} from "../../lib/playback-ranges";
import { MarkerOverlay } from "./MarkerOverlay";
import { ScrubBar } from "./ScrubBar";
import { TranscriptSubtitle } from "./TranscriptSubtitle";

export interface VideoPlayerHandle {
  getCurrentTime: () => number;
  getCurrentFrame: () => number;
  seek: (time: number) => void;
  getVideoElement: () => HTMLVideoElement | null;
  togglePlay: () => void;
  stepFrame: (delta: number) => void;
}

interface VideoPlayerProps {
  clips: Clip[];
  activeClipId: string | null;
  onClipChange: (clipId: string) => void;
  markers: Marker[];
  markerMode: boolean;
  selectedMarkerId: string | null;
  clipEdit?: ClipEdit;
  onAddSpatialMarker: (time: number, frame: number, x: number, y: number, clipId: string) => void;
  onAddTemporalMarker: (time: number, frame: number, clipId: string) => void;
  onSelectMarker: (id: string | null) => void;
  onMoveMarker: (id: string, x: number, y: number) => void;
  wordCuts?: WordCut[];
  onSplit?: (time: number) => void;
  onRemoveSplit?: (index: number) => void;
}

export const VideoPlayer = forwardRef<VideoPlayerHandle, VideoPlayerProps>(
  function VideoPlayer(
    {
      clips,
      activeClipId,
      onClipChange,
      markers,
      markerMode,
      selectedMarkerId,
      clipEdit,
      wordCuts,
      onAddSpatialMarker,
      onAddTemporalMarker,
      onSelectMarker,
      onMoveMarker,
      onSplit,
      onRemoveSplit,
    },
    ref,
  ) {
    const videoRef = useRef<HTMLVideoElement>(null);
    const [playing, setPlaying] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const [duration, setDuration] = useState(0);
    const [currentFrame, setCurrentFrame] = useState(0);
    const [noPlayableContent, setNoPlayableContent] = useState(false);

    const activeClip = clips.find((c) => c.id === activeClipId) || clips[0];
    const fps = activeClip?.metadata?.fps || 30;
    const epsilon = 0.5 / fps;
    const videoSrc = activeClip ? mediaUrl(activeClip.symlink_path) : null;
    const rawSegments = activeClip?.transcript?.segments;
    const transcriptSegments = Array.isArray(rawSegments) ? rawSegments : [];

    // Compute playback constraints from edits
    const constraints: PlaybackConstraints = useMemo(
      () => computePlaybackRanges(clipEdit, wordCuts ?? [], activeClip?.id ?? "", duration),
      [clipEdit, wordCuts, activeClip?.id, duration],
    );

    useImperativeHandle(ref, () => ({
      getCurrentTime: () => currentTime,
      getCurrentFrame: () => currentFrame,
      seek: (time: number) => {
        const video = videoRef.current;
        if (!video) return;
        const clamped = clampToPlayable(time, constraints, 1, epsilon);
        if (video.readyState >= 1) {
          video.currentTime = clamped;
        } else {
          const onLoaded = () => {
            video.currentTime = clamped;
            video.removeEventListener("loadedmetadata", onLoaded);
          };
          video.addEventListener("loadedmetadata", onLoaded);
        }
      },
      getVideoElement: () => videoRef.current,
      togglePlay: () => togglePlay(),
      stepFrame: (delta: number) => stepFrame(delta),
    }));

    const togglePlay = useCallback(() => {
      const video = videoRef.current;
      if (!video) return;
      if (video.paused) {
        // Before playing, ensure we're in a playable region
        const t = video.currentTime;
        if (t < constraints.playableStart || t >= constraints.playableEnd) {
          video.currentTime = constraints.playableStart;
        }
        const skip = findContainingSkipRange(t, constraints.skipRanges, epsilon);
        if (skip) {
          video.currentTime = skip.end;
        }
        video.play();
        setPlaying(true);
      } else {
        video.pause();
        setPlaying(false);
      }
    }, [constraints, epsilon]);

    const stepFrame = useCallback(
      (delta: number) => {
        const video = videoRef.current;
        if (!video) return;
        video.pause();
        setPlaying(false);
        const raw = video.currentTime + delta / fps;
        const direction: 1 | -1 = delta >= 0 ? 1 : -1;
        const newTime = clampToPlayable(raw, constraints, direction, epsilon);
        video.currentTime = newTime;
      },
      [fps, constraints, epsilon],
    );

    const seek = useCallback(
      (time: number) => {
        const video = videoRef.current;
        if (!video) return;
        video.currentTime = clampToPlayable(time, constraints, 1, epsilon);
      },
      [constraints, epsilon],
    );

    // Reload video element when source changes
    useEffect(() => {
      const video = videoRef.current;
      if (!video) return;
      video.load();
      setPlaying(false);
      setCurrentTime(0);
      setCurrentFrame(0);
      setDuration(0);
      setNoPlayableContent(false);
    }, [videoSrc]);

    // Frame-accurate time tracking + skip enforcement
    useEffect(() => {
      const video = videoRef.current;
      if (!video) return;

      const enforceConstraints = (t: number) => {
        // Before playable start
        if (t < constraints.playableStart - epsilon) {
          video.currentTime = constraints.playableStart;
          return;
        }
        // Past playable end
        if (t >= constraints.playableEnd - epsilon) {
          video.pause();
          setPlaying(false);
          return;
        }
        // Inside a skip range
        const skip = findContainingSkipRange(t, constraints.skipRanges, epsilon);
        if (skip) {
          // If skip.end is at or past playableEnd, pause
          if (skip.end >= constraints.playableEnd - epsilon) {
            video.pause();
            setPlaying(false);
          } else {
            video.currentTime = skip.end;
          }
        }
      };

      // Use requestVideoFrameCallback if available
      if ("requestVideoFrameCallback" in (video as HTMLVideoElement)) {
        let handle: number;
        const onFrame = (_now: number, metadata: { mediaTime: number }) => {
          setCurrentTime(metadata.mediaTime);
          setCurrentFrame(timeToFrame(metadata.mediaTime, fps));
          if (!video.paused) {
            enforceConstraints(metadata.mediaTime);
          }
          handle = (video as any).requestVideoFrameCallback(onFrame);
        };
        handle = (video as any).requestVideoFrameCallback(onFrame);
        return () => {
          (video as any).cancelVideoFrameCallback(handle);
        };
      }

      // Fallback to timeupdate
      const onTimeUpdate = () => {
        const t = video.currentTime;
        setCurrentTime(t);
        setCurrentFrame(timeToFrame(t, fps));
        if (!video.paused) {
          enforceConstraints(t);
        }
      };
      video.addEventListener("timeupdate", onTimeUpdate);
      return () => video.removeEventListener("timeupdate", onTimeUpdate);
    }, [fps, activeClipId, constraints, epsilon]);

    const handleCanvasClick = useCallback(
      (normalizedX: number, normalizedY: number) => {
        if (!markerMode || !activeClip) return;
        onAddSpatialMarker(currentTime, currentFrame, normalizedX, normalizedY, activeClip.id);
      },
      [markerMode, activeClip, currentTime, currentFrame, onAddSpatialMarker],
    );

    const handleScrubBarMarkerClick = useCallback(
      (time: number) => {
        if (!markerMode || !activeClip) return;
        const frame = timeToFrame(time, fps);
        onAddTemporalMarker(time, frame, activeClip.id);
      },
      [markerMode, activeClip, fps, onAddTemporalMarker],
    );

    if (!activeClip || !videoSrc) {
      return (
        <div className="h-full flex items-center justify-center text-cp-text-muted text-sm">
          No video to play
        </div>
      );
    }

    if (noPlayableContent && duration > 0) {
      return (
        <div className="h-full flex items-center justify-center text-cp-text-muted text-sm">
          No playable content — all regions are cut or trimmed
        </div>
      );
    }

    const clipMarkers = markers.filter((m) => m.source_clip_id === activeClip.id);

    return (
      <div className="h-full flex flex-col bg-black">
        {/* Source selector for bundles */}
        {clips.length > 1 && (
          <div className="flex items-center gap-2 px-3 py-1 bg-cp-bg-elevated">
            <span className="text-xs text-cp-text-muted">Source:</span>
            <select
              value={activeClip.id}
              onChange={(e) => onClipChange(e.target.value)}
              className="bg-cp-bg border border-cp-border rounded px-2 py-0.5 text-xs"
            >
              {clips.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.id} ({c.type})
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Video + overlay */}
        <div className="relative flex-1 flex items-center justify-center overflow-hidden">
          <video
            ref={videoRef}
            src={videoSrc}
            className="max-w-full max-h-full"
            onLoadedMetadata={() => {
              if (!videoRef.current) return;
              const dur = videoRef.current.duration;
              setDuration(dur);
              // Compute constraints with fresh duration for initial seek
              const c = computePlaybackRanges(clipEdit, wordCuts ?? [], activeClip?.id ?? "", dur);
              setNoPlayableContent(!hasPlayableContent(c));
              if (c.playableStart > 0) {
                videoRef.current.currentTime = c.playableStart;
              }
            }}
            onEnded={() => setPlaying(false)}
            preload="auto"
          />
          <MarkerOverlay
            videoRef={videoRef}
            markers={clipMarkers}
            selectedMarkerId={selectedMarkerId}
            markerMode={markerMode}
            currentTime={currentTime}
            fps={fps}
            onCanvasClick={handleCanvasClick}
            onSelectMarker={onSelectMarker}
            onMoveMarker={onMoveMarker}
          />
        </div>

        {/* Subtitle */}
        <TranscriptSubtitle
          segments={transcriptSegments}
          currentTime={currentTime}
        />

        {/* Scrub bar */}
        <ScrubBar
          currentTime={currentTime}
          duration={duration}
          markers={clipMarkers}
          markerMode={markerMode}
          clipEdit={clipEdit}
          wordCuts={wordCuts}
          clipId={activeClip.id}
          onSeek={seek}
          onMarkerClick={handleScrubBarMarkerClick}
          onRemoveSplit={onRemoveSplit}
        />

        {/* Controls */}
        <div className="flex items-center justify-center gap-3 px-4 py-2 bg-cp-bg-elevated">
          <button
            onClick={() => stepFrame(-1)}
            className="p-1 hover:text-cp-primary transition-colors"
            title="Previous frame (←)"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>

          <button
            onClick={togglePlay}
            className="p-2 hover:text-cp-primary transition-colors"
            title="Play/Pause (Space)"
          >
            {playing ? (
              <Pause className="w-5 h-5" />
            ) : (
              <Play className="w-5 h-5 fill-current" />
            )}
          </button>

          <button
            onClick={() => stepFrame(1)}
            className="p-1 hover:text-cp-primary transition-colors"
            title="Next frame (→)"
          >
            <ChevronRight className="w-4 h-4" />
          </button>

          <div className="ml-4 font-code text-xs text-cp-text-secondary tabular-nums">
            {formatFrameTimecode(currentTime, fps)}
          </div>

          <div className="ml-2 text-xs text-cp-text-muted tabular-nums">
            F{currentFrame}
          </div>

          {/* NLE tools */}
          {onSplit && (
            <div className="ml-4 flex items-center gap-1 border-l border-cp-border pl-4">
              <button
                onClick={() => onSplit(currentTime)}
                className="p-1 hover:text-cp-accent transition-colors"
                title="Split at playhead (S)"
              >
                <Scissors className="w-4 h-4" />
              </button>
            </div>
          )}

          {markerMode && (
            <div className="ml-4 text-xs text-cp-accent">
              MARKER MODE
            </div>
          )}
        </div>
      </div>
    );
  },
);
