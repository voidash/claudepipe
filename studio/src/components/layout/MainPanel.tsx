import { useState, useCallback } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { Layers, Play, Search } from "lucide-react";
import type { FootageManifest, Clip, UnitEntry } from "../../types/manifest";
import type { EditUnit, ClaudeNote, Marker, WordCut, AddedMedia, ClipEdit } from "../../types/edit-manifest";
import type { VideoPlayerHandle } from "../player/VideoPlayer";
import { ElementsTab } from "../tabs/ElementsTab";
import { PlayerTab } from "../tabs/PlayerTab";
import { PrecisionTab } from "../tabs/PrecisionTab";
import { InstructionsPanel } from "../instructions/InstructionsPanel";
import { ErrorBoundary } from "../ErrorBoundary";
import { cn } from "../../lib/cn";

type TabId = "elements" | "player" | "precision";

interface MainPanelProps {
  unitManifest: FootageManifest | null;
  unitManifestLoading: boolean;
  unitManifestError: string | null;
  selectedUnit: UnitEntry | null;
  editUnit: EditUnit | null;
  claudeNote: ClaudeNote | null;
  selectedUnitId: string | null;
  clips: Clip[];
  activeClipId: string | null;
  onClipChange: (clipId: string) => void;
  markers: Marker[];
  markerMode: boolean;
  selectedMarkerId: string | null;
  onAddSpatialMarker: (time: number, frame: number, x: number, y: number, clipId: string) => void;
  onAddTemporalMarker: (time: number, frame: number, clipId: string) => void;
  onSelectMarker: (id: string | null) => void;
  onMoveMarker: (id: string, x: number, y: number) => void;
  onRenameMarker: (id: string, name: string) => void;
  onDeleteMarker: (id: string) => void;
  clipEdit?: ClipEdit;
  wordCuts: WordCut[];
  onWordCutsChange: (cuts: WordCut[]) => void;
  discardedClips: string[];
  addedMedia: AddedMedia[];
  onRemoveMedia: (index: number) => void;
  onToggleDiscardClip: (clipId: string) => void;
  onInstructionsChange: (unitId: string, instructions: string) => void;
  onDropFiles: (files: File[]) => void;
  onPlayClip: (clipId: string) => void;
  onSplit?: (time: number) => void;
  onRemoveSplit?: (index: number) => void;
  onMoveClip?: (clipId: string, toUnitId: string) => void;
  availableUnits?: { id: string; name: string }[];
  playerRef: React.RefObject<VideoPlayerHandle | null>;
}

const tabs: { id: TabId; label: string; icon: typeof Layers }[] = [
  { id: "elements", label: "Elements", icon: Layers },
  { id: "player", label: "Player", icon: Play },
  { id: "precision", label: "Precision", icon: Search },
];

export function MainPanel({
  unitManifest,
  unitManifestLoading,
  unitManifestError,
  selectedUnit,
  editUnit,
  claudeNote,
  selectedUnitId,
  clips,
  activeClipId,
  onClipChange,
  markers,
  markerMode,
  selectedMarkerId,
  onAddSpatialMarker,
  onAddTemporalMarker,
  onSelectMarker,
  onMoveMarker,
  onRenameMarker,
  onDeleteMarker,
  wordCuts,
  onWordCutsChange,
  discardedClips,
  addedMedia,
  onRemoveMedia,
  onToggleDiscardClip,
  clipEdit,
  onInstructionsChange,
  onDropFiles,
  onPlayClip,
  onSplit,
  onRemoveSplit,
  onMoveClip,
  availableUnits,
  playerRef,
}: MainPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>("elements");

  const handlePlayClip = (clipId: string) => {
    onPlayClip(clipId);
    setActiveTab("player");
  };

  const handleSeekToMarker = useCallback((time: number) => {
    playerRef.current?.seek(time);
    setActiveTab("player");
  }, [playerRef]);

  return (
    <PanelGroup direction="vertical">
      <Panel defaultSize={60} minSize={30}>
        <div className="h-full flex flex-col">
          {/* Tab bar */}
          <div className="flex border-b border-cp-border bg-cp-bg-elevated">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={cn(
                    "flex items-center gap-1.5 px-4 py-2 text-sm transition-colors border-b-2",
                    activeTab === tab.id
                      ? "border-cp-primary text-cp-text"
                      : "border-transparent text-cp-text-muted hover:text-cp-text-secondary",
                  )}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {tab.label}
                </button>
              );
            })}
          </div>

          {/* Tab content — all tabs stay mounted to preserve refs and state */}
          <div className="flex-1 min-h-0 relative">
            <div className={cn("absolute inset-0", activeTab !== "elements" && "hidden")}>
              <ErrorBoundary>
                <ElementsTab
                  unitManifest={unitManifest}
                  unit={selectedUnit}
                  loading={unitManifestLoading}
                  error={unitManifestError}
                  discardedClips={discardedClips}
                  clipEdits={editUnit?.clip_edits}
                  wordCuts={wordCuts}
                  addedMedia={addedMedia}
                  availableUnits={availableUnits}
                  markers={markers}
                  onRemoveMedia={onRemoveMedia}
                  onPlayClip={handlePlayClip}
                  onDropFiles={onDropFiles}
                  onMoveClip={onMoveClip}
                  onToggleDiscard={onToggleDiscardClip}
                  onSeekToMarker={handleSeekToMarker}
                />
              </ErrorBoundary>
            </div>
            <div className={cn("absolute inset-0", activeTab !== "player" && "hidden")}>
              <ErrorBoundary>
                <PlayerTab
                  ref={playerRef}
                  clips={clips}
                  activeClipId={activeClipId}
                  onClipChange={onClipChange}
                  markers={markers}
                  markerMode={markerMode}
                  selectedMarkerId={selectedMarkerId}
                  clipEdit={clipEdit}
                  wordCuts={wordCuts}
                  onWordCutsChange={onWordCutsChange}
                  onAddSpatialMarker={onAddSpatialMarker}
                  onAddTemporalMarker={onAddTemporalMarker}
                  onSelectMarker={onSelectMarker}
                  onMoveMarker={onMoveMarker}
                  onRenameMarker={onRenameMarker}
                  onDeleteMarker={onDeleteMarker}
                  onSplit={onSplit}
                  onRemoveSplit={onRemoveSplit}
                />
              </ErrorBoundary>
            </div>
            <div className={cn("absolute inset-0", activeTab !== "precision" && "hidden")}>
              <ErrorBoundary>
                <PrecisionTab
                  playerRef={playerRef}
                  isActive={activeTab === "precision"}
                  markers={markers}
                  markerMode={markerMode}
                  selectedMarkerId={selectedMarkerId}
                  onAddSpatialMarker={onAddSpatialMarker}
                  onSelectMarker={onSelectMarker}
                  onMoveMarker={onMoveMarker}
                  activeClipId={activeClipId || ""}
                />
              </ErrorBoundary>
            </div>
          </div>
        </div>
      </Panel>

      <PanelResizeHandle className="h-1 bg-cp-border hover:bg-cp-primary transition-colors cursor-row-resize" />

      <Panel defaultSize={40} minSize={20}>
        <InstructionsPanel
          unitId={selectedUnitId}
          editUnit={editUnit}
          claudeNote={claudeNote}
          markers={markers}
          onInstructionsChange={onInstructionsChange}
          onMarkerSeek={(time) => playerRef.current?.seek(time)}
        />
      </Panel>
    </PanelGroup>
  );
}
