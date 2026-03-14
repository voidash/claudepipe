import { useRef, useState, useEffect, useCallback, forwardRef, useImperativeHandle } from "react";
import { MapPin, MessageSquareText } from "lucide-react";
import type { Clip } from "../../types/manifest";
import type { Marker, WordCut, ClipEdit } from "../../types/edit-manifest";
import { fetchTranscript, type TranscriptData } from "../../api/client";
import { VideoPlayer, type VideoPlayerHandle } from "../player/VideoPlayer";
import { AudioPlayer } from "../player/AudioPlayer";
import { MarkerList } from "../player/MarkerList";
import { TranscriptPanel } from "../player/TranscriptPanel";
import { cn } from "../../lib/cn";

function isAudioOnly(clip: Clip | undefined): boolean {
  if (!clip) return false;
  const { width, height, codec_video } = clip.metadata;
  // Positive dimensions means it has video content
  if (width > 0 && height > 0) return false;
  // Explicit video codec means it has video
  if (codec_video) return false;
  return true;
}

type BottomTab = "transcript" | "markers";

interface PlayerTabProps {
  clips: Clip[];
  activeClipId: string | null;
  onClipChange: (clipId: string) => void;
  markers: Marker[];
  markerMode: boolean;
  selectedMarkerId: string | null;
  clipEdit?: ClipEdit;
  wordCuts: WordCut[];
  onWordCutsChange: (cuts: WordCut[]) => void;
  onAddSpatialMarker: (time: number, frame: number, x: number, y: number, clipId: string) => void;
  onAddTemporalMarker: (time: number, frame: number, clipId: string) => void;
  onSelectMarker: (id: string | null) => void;
  onMoveMarker: (id: string, x: number, y: number) => void;
  onRenameMarker: (id: string, name: string) => void;
  onDeleteMarker: (id: string) => void;
  onSplit?: (time: number) => void;
  onRemoveSplit?: (index: number) => void;
}

export const PlayerTab = forwardRef<VideoPlayerHandle, PlayerTabProps>(
  function PlayerTab(
    {
      clips,
      activeClipId,
      onClipChange,
      markers,
      markerMode,
      selectedMarkerId,
      clipEdit,
      wordCuts,
      onWordCutsChange,
      onAddSpatialMarker,
      onAddTemporalMarker,
      onSelectMarker,
      onMoveMarker,
      onRenameMarker,
      onDeleteMarker,
      onSplit,
      onRemoveSplit,
    },
    ref,
  ) {
    const playerRef = useRef<VideoPlayerHandle>(null);
    const [bottomTab, setBottomTab] = useState<BottomTab>("transcript");
    const [transcript, setTranscript] = useState<TranscriptData | null>(null);
    const [currentTime, setCurrentTime] = useState(0);

    useImperativeHandle(ref, () => ({
      getCurrentTime: () => playerRef.current?.getCurrentTime() ?? 0,
      getCurrentFrame: () => playerRef.current?.getCurrentFrame() ?? 0,
      seek: (time) => playerRef.current?.seek(time),
      getVideoElement: () => playerRef.current?.getVideoElement() ?? null,
      togglePlay: () => playerRef.current?.togglePlay(),
      stepFrame: (delta) => playerRef.current?.stepFrame(delta),
    }));

    const activeClip = clips.find((c) => c.id === activeClipId) || clips[0];
    const audioOnly = isAudioOnly(activeClip);
    const resolvedClipId = activeClip?.id || null;

    // Load transcript when active clip changes
    useEffect(() => {
      if (!resolvedClipId) {
        setTranscript(null);
        return;
      }
      let cancelled = false;
      fetchTranscript(resolvedClipId)
        .then((data) => {
          if (!cancelled) setTranscript(data);
        })
        .catch(() => {
          if (!cancelled) setTranscript(null);
        });
      return () => { cancelled = true; };
    }, [resolvedClipId]);

    // Poll current time from player for transcript sync
    useEffect(() => {
      const interval = setInterval(() => {
        const t = playerRef.current?.getCurrentTime() ?? 0;
        setCurrentTime(t);
      }, 100);
      return () => clearInterval(interval);
    }, []);

    const handleTranscriptSeek = useCallback((time: number) => {
      playerRef.current?.seek(time);
    }, []);

    return (
      <div className="h-full flex flex-col">
        <div className="flex-1 min-h-0">
          {audioOnly ? (
            <AudioPlayer
              ref={playerRef}
              clips={clips}
              activeClipId={activeClipId}
              onClipChange={onClipChange}
              markers={markers}
              markerMode={markerMode}
              onAddTemporalMarker={onAddTemporalMarker}
            />
          ) : (
            <VideoPlayer
              ref={playerRef}
              clips={clips}
              activeClipId={activeClipId}
              onClipChange={onClipChange}
              markers={markers}
              markerMode={markerMode}
              selectedMarkerId={selectedMarkerId}
              clipEdit={clipEdit}
              wordCuts={wordCuts}
              onAddSpatialMarker={onAddSpatialMarker}
              onAddTemporalMarker={onAddTemporalMarker}
              onSelectMarker={onSelectMarker}
              onMoveMarker={onMoveMarker}
              onSplit={onSplit}
              onRemoveSplit={onRemoveSplit}
            />
          )}
        </div>

        {/* Bottom panel: Transcript / Markers tabs */}
        <div className="h-40 border-t border-cp-border flex flex-col bg-cp-bg-elevated">
          <div className="flex border-b border-cp-border shrink-0">
            <button
              onClick={() => setBottomTab("transcript")}
              className={cn(
                "flex items-center gap-1 px-3 py-1 text-xs transition-colors border-b-2",
                bottomTab === "transcript"
                  ? "border-cp-primary text-cp-text"
                  : "border-transparent text-cp-text-muted hover:text-cp-text-secondary",
              )}
            >
              <MessageSquareText className="w-3 h-3" />
              Transcript
            </button>
            <button
              onClick={() => setBottomTab("markers")}
              className={cn(
                "flex items-center gap-1 px-3 py-1 text-xs transition-colors border-b-2",
                bottomTab === "markers"
                  ? "border-cp-primary text-cp-text"
                  : "border-transparent text-cp-text-muted hover:text-cp-text-secondary",
              )}
            >
              <MapPin className="w-3 h-3" />
              Markers
              {markers.length > 0 && (
                <span className="text-cp-accent ml-0.5">{markers.length}</span>
              )}
            </button>
          </div>

          <div className="flex-1 min-h-0 overflow-hidden">
            {bottomTab === "transcript" ? (
              <TranscriptPanel
                transcript={transcript}
                currentTime={currentTime}
                clipId={resolvedClipId}
                wordCuts={wordCuts}
                onSeek={handleTranscriptSeek}
                onWordCutsChange={onWordCutsChange}
              />
            ) : (
              <div className="h-full overflow-y-auto">
                <MarkerList
                  markers={markers}
                  selectedMarkerId={selectedMarkerId}
                  onSelect={onSelectMarker}
                  onRename={onRenameMarker}
                  onDelete={onDeleteMarker}
                  onSeek={(time) => playerRef.current?.seek(time)}
                />
              </div>
            )}
          </div>
        </div>
      </div>
    );
  },
);
