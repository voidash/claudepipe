import { useRef, useState, useCallback, useEffect, forwardRef, useImperativeHandle } from "react";
import WaveSurfer from "wavesurfer.js";
import {
  Play,
  Pause,
  ChevronLeft,
  ChevronRight,
  Volume2,
} from "lucide-react";
import type { Clip } from "../../types/manifest";
import type { Marker } from "../../types/edit-manifest";
import { formatFrameTimecode, timeToFrame } from "../../lib/frame-utils";
import { mediaUrl } from "../../api/client";
import { ScrubBar } from "./ScrubBar";
import type { VideoPlayerHandle } from "./VideoPlayer";

interface AudioPlayerProps {
  clips: Clip[];
  activeClipId: string | null;
  onClipChange: (clipId: string) => void;
  markers: Marker[];
  markerMode: boolean;
  onAddTemporalMarker: (time: number, frame: number, clipId: string) => void;
}

export const AudioPlayer = forwardRef<VideoPlayerHandle, AudioPlayerProps>(
  function AudioPlayer(
    {
      clips,
      activeClipId,
      onClipChange,
      markers,
      markerMode,
      onAddTemporalMarker,
    },
    ref,
  ) {
    const containerRef = useRef<HTMLDivElement>(null);
    const wsRef = useRef<WaveSurfer | null>(null);
    const [playing, setPlaying] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const [duration, setDuration] = useState(0);

    const activeClip = clips.find((c) => c.id === activeClipId) || clips[0];
    const fps = activeClip?.metadata?.fps || 30;
    const audioSrc = activeClip
      ? mediaUrl(activeClip.audio?.denoised_path || activeClip.audio?.extracted_path || activeClip.symlink_path)
      : null;

    useImperativeHandle(ref, () => ({
      getCurrentTime: () => wsRef.current?.getCurrentTime() ?? currentTime,
      getCurrentFrame: () => timeToFrame(wsRef.current?.getCurrentTime() ?? currentTime, fps),
      seek: (time: number) => {
        const d = wsRef.current?.getDuration() || duration;
        if (d > 0) wsRef.current?.seekTo(Math.min(1, Math.max(0, time / d)));
      },
      getVideoElement: () => null,
      togglePlay: () => wsRef.current?.playPause(),
      stepFrame: (delta: number) => {
        const ws = wsRef.current;
        if (!ws) return;
        const d = ws.getDuration();
        const t = ws.getCurrentTime();
        const newTime = Math.max(0, Math.min(d, t + delta / fps));
        if (d > 0) ws.seekTo(newTime / d);
      },
    }));

    // Initialize wavesurfer
    useEffect(() => {
      if (!containerRef.current || !audioSrc) return;

      const ws = WaveSurfer.create({
        container: containerRef.current,
        waveColor: "#B8B8D0",
        progressColor: "#FF6B35",
        cursorColor: "#F7C948",
        barWidth: 2,
        barGap: 1,
        barRadius: 2,
        height: 128,
        normalize: true,
        url: audioSrc,
      });

      ws.on("ready", () => setDuration(ws.getDuration()));
      ws.on("timeupdate", (t: number) => setCurrentTime(t));
      ws.on("play", () => setPlaying(true));
      ws.on("pause", () => setPlaying(false));
      ws.on("finish", () => setPlaying(false));

      wsRef.current = ws;

      return () => {
        ws.destroy();
        wsRef.current = null;
      };
    }, [audioSrc]);

    const togglePlay = useCallback(() => {
      wsRef.current?.playPause();
    }, []);

    const stepFrame = useCallback(
      (delta: number) => {
        const ws = wsRef.current;
        if (!ws) return;
        const d = ws.getDuration();
        const t = ws.getCurrentTime();
        const newTime = Math.max(0, Math.min(d, t + delta / fps));
        if (d > 0) ws.seekTo(newTime / d);
      },
      [fps],
    );

    const seek = useCallback(
      (time: number) => {
        const d = wsRef.current?.getDuration() || duration;
        if (d > 0) wsRef.current?.seekTo(Math.min(1, Math.max(0, time / d)));
      },
      [duration],
    );

    const handleScrubBarMarkerClick = useCallback(
      (time: number) => {
        if (!markerMode || !activeClip) return;
        const frame = timeToFrame(time, fps);
        onAddTemporalMarker(time, frame, activeClip.id);
      },
      [markerMode, activeClip, fps, onAddTemporalMarker],
    );

    if (!activeClip || !audioSrc) {
      return (
        <div className="h-full flex items-center justify-center text-cp-text-muted text-sm">
          No audio to play
        </div>
      );
    }

    const clipMarkers = markers.filter((m) => m.source_clip_id === activeClip.id);
    const currentFrame = timeToFrame(currentTime, fps);

    return (
      <div className="h-full flex flex-col bg-cp-bg">
        {/* Source selector */}
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

        {/* Waveform */}
        <div className="flex-1 flex items-center justify-center p-4">
          <div className="w-full">
            <div className="flex items-center gap-2 mb-2">
              <Volume2 className="w-4 h-4 text-cp-text-muted" />
              <span className="text-xs text-cp-text-secondary">{activeClip.id}</span>
            </div>
            <div ref={containerRef} className="w-full rounded-md overflow-hidden" />
          </div>
        </div>

        {/* Scrub bar */}
        <ScrubBar
          currentTime={currentTime}
          duration={duration}
          markers={clipMarkers}
          markerMode={markerMode}
          onSeek={seek}
          onMarkerClick={handleScrubBarMarkerClick}
        />

        {/* Controls */}
        <div className="flex items-center justify-center gap-3 px-4 py-2 bg-cp-bg-elevated">
          <button
            onClick={() => stepFrame(-1)}
            className="p-1 hover:text-cp-primary transition-colors"
            title="Previous frame"
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
            title="Next frame"
          >
            <ChevronRight className="w-4 h-4" />
          </button>

          <div className="ml-4 font-code text-xs text-cp-text-secondary tabular-nums">
            {formatFrameTimecode(currentTime, fps)}
          </div>

          <div className="ml-2 text-xs text-cp-text-muted tabular-nums">
            F{currentFrame}
          </div>

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
