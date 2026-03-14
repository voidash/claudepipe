import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useManifest, useUnitManifest } from "./hooks/useManifest";
import { useEditManifest } from "./hooks/useEditManifest";
import { useMarkers } from "./hooks/useMarkers";
import { useKeyboard } from "./hooks/useKeyboard";
import { resetMarkerCounter } from "./lib/marker-utils";
import { uploadFile } from "./api/client";
import { AppShell } from "./components/layout/AppShell";
import { Sidebar } from "./components/layout/Sidebar";
import { MainPanel } from "./components/layout/MainPanel";
import { StatusBar } from "./components/layout/StatusBar";
import { ImportPage } from "./components/import/ImportPage";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { KeyboardHelp } from "./components/KeyboardHelp";
import type { VideoPlayerHandle } from "./components/player/VideoPlayer";
import type { Clip } from "./types/manifest";
import type { AddedMedia } from "./types/edit-manifest";

type AppMode = "loading" | "import" | "studio";

/** Convert an AddedMedia entry into a minimal Clip so it flows through the existing player pipeline. */
function mediaToSyntheticClip(m: AddedMedia): Clip {
  const stem = m.filename.replace(/\.[^.]+$/, "").replace(/[^a-zA-Z0-9_-]/g, "_");
  return {
    id: `added_${stem}`,
    source_path: m.path,
    symlink_path: m.path,
    type: "camera",
    classification_confidence: 1,
    metadata: {
      duration_seconds: m.duration_seconds ?? 0,
      width: m.width ?? 1920,
      height: m.height ?? 1080,
      fps: m.fps ?? 30,
      fps_rational: m.fps ? `${m.fps}/1` : "30/1",
      codec_video: m.codec_video ?? (m.type === "audio" ? "" : "h264"),
      codec_audio: "aac",
      audio_channels: 2,
      audio_sample_rate: 48000,
      bit_rate_bps: 0,
      creation_time: m.added_at,
      camera_model: "",
      rotation: 0,
      file_size_bytes: 0,
      has_audio: m.type !== "image",
    },
    audio: { extracted_path: "", denoised_path: "", noise_removal_applied: false, noise_removal_engine: "", sample_rate: 0, duration_seconds: m.duration_seconds ?? 0 },
    transcript: { path: "", engine: "", segments: [] },
    vad: { path: "", engine: "", speech_segments: [], silence_segments: [], speech_ratio: 0 },
    pitch: { path: "", mean_hz: 0, std_hz: 0, emphasis_points: [] },
    scenes: { path: "", boundaries: [] },
    frames: { dir: "", count: 0, extracted: [] },
    yolo: { path: "", model: "", detections_by_frame: {}, tracking_summary: { primary_subject_bbox_median: [], subject_movement_range: { x_min: 0, x_max: 0, y_min: 0, y_max: 0 } } },
    vision: { path: "", analyses: [] },
    screen_sync: null,
  };
}

interface ModeInfo {
  mode: "import" | "studio";
  project_root: string | null;
  cwd: string;
}

export default function App() {
  const [appMode, setAppMode] = useState<AppMode>("loading");
  const [modeInfo, setModeInfo] = useState<ModeInfo | null>(null);

  // Detect mode from server
  useEffect(() => {
    fetch("/api/mode")
      .then((res) => res.json())
      .then((data: ModeInfo) => {
        setModeInfo(data);
        setAppMode(data.mode);
      })
      .catch(() => {
        // If server isn't reachable, assume import mode
        setModeInfo({ mode: "import", project_root: null, cwd: "." });
        setAppMode("import");
      });
  }, []);

  const handleProjectCreated = useCallback((projectRoot: string) => {
    // Signal to the user that the project was created
    // The GUI's job is done — Claude CLI takes over
    setAppMode("done" as AppMode);
    // Write a marker file so the CLI knows the project is ready
    document.title = `Project created: ${projectRoot}`;
    // Show confirmation in the UI
    setModeInfo((prev) => prev ? { ...prev, project_root: projectRoot } : null);
  }, []);

  if (appMode === "loading") {
    return (
      <div className="h-screen flex items-center justify-center bg-cp-bg">
        <div className="text-center">
          <div className="text-lg font-heading text-cp-primary mb-2">claudepipe</div>
          <div className="text-sm text-cp-text-muted">Connecting...</div>
        </div>
      </div>
    );
  }

  if (appMode === "import") {
    return (
      <ImportPage
        defaultProjectDir={modeInfo?.cwd || "."}
        onProjectCreated={handleProjectCreated}
      />
    );
  }

  // "done" state — project created, waiting for user to close
  if ((appMode as string) === "done") {
    return (
      <div className="h-screen flex items-center justify-center bg-cp-bg">
        <div className="text-center max-w-md">
          <div className="text-2xl font-heading text-cp-success mb-3">Project Created</div>
          <div className="text-sm text-cp-text-secondary mb-2">
            {modeInfo?.project_root}
          </div>
          <div className="text-sm text-cp-text-muted">
            You can close this window. Return to Claude CLI to run the pipeline.
          </div>
          <div className="mt-6 p-4 bg-cp-bg-elevated rounded-lg border border-cp-border">
            <div className="text-xs text-cp-text-muted mb-1">Copy this to your terminal:</div>
            <code className="text-sm text-cp-primary font-code">
              /footage
            </code>
          </div>
        </div>
      </div>
    );
  }

  // Studio mode
  return (
    <ErrorBoundary>
      <StudioApp />
    </ErrorBoundary>
  );
}

function StudioApp() {
  const { manifest, loading: manifestLoading, error: manifestError } = useManifest();
  const {
    editManifest,
    loading: editLoading,
    error: editError,
    saving,
    updateUnitOrder,
    updateUnitInstructions,
    updateUnitMarkers,
    updateUnitWordCuts,
    toggleDiscardClip,
    addUnitMedia,
    removeUnitMedia,
    insertUnit,
    deleteUnit,
    splitClipAt,
    removeSplit,
    addDeletedRange,
    removeDeletedRange,
    moveClipToUnit,
    endSession,
    initialize,
  } = useEditManifest();

  const [selectedUnitId, setSelectedUnitId] = useState<string | null>(null);
  const [activeClipId, setActiveClipId] = useState<string | null>(null);
  const [showEndConfirm, setShowEndConfirm] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  const playerRef = useRef<VideoPlayerHandle>(null);

  // Don't fetch unit manifest for inserted units that haven't requested pipeline (no unit directory on disk).
  // Pipeline-requested inserted units DO have a unit directory, so fetch their manifest.
  const skipUnitManifest = selectedUnitId
    && editManifest?.units[selectedUnitId]?.is_inserted
    && !editManifest?.units[selectedUnitId]?.pipeline_requested;
  const { unitManifest, loading: unitManifestLoading, error: unitManifestError } =
    useUnitManifest(skipUnitManifest ? null : selectedUnitId);

  useEffect(() => {
    if (manifest && !editManifest && !editLoading) {
      initialize();
    }
  }, [manifest, editManifest, editLoading, initialize]);

  useEffect(() => {
    if (editManifest && !selectedUnitId && editManifest.unit_order.length > 0) {
      setSelectedUnitId(editManifest.unit_order[0]);
    }
  }, [editManifest, selectedUnitId]);

  const currentEditUnit = selectedUnitId && editManifest
    ? editManifest.units[selectedUnitId]
    : null;

  // Set active clip when unit changes — from manifest or synthesized from added media
  useEffect(() => {
    if (unitManifest?.clips?.length) {
      setActiveClipId(unitManifest.clips[0].id);
    } else if (currentEditUnit?.added_media?.length) {
      const firstPlayable = currentEditUnit.added_media.find(
        (m) => m.type === "video" || m.type === "audio",
      );
      if (firstPlayable) {
        const stem = firstPlayable.filename.replace(/\.[^.]+$/, "").replace(/[^a-zA-Z0-9_-]/g, "_");
        setActiveClipId(`added_${stem}`);
      }
    }
  }, [unitManifest, currentEditUnit?.added_media]);

  const handleMarkersChange = useCallback(
    (markers: any[]) => {
      if (selectedUnitId) updateUnitMarkers(selectedUnitId, markers);
    },
    [selectedUnitId, updateUnitMarkers],
  );

  const handleWordCutsChange = useCallback(
    (cuts: any[]) => {
      if (selectedUnitId) updateUnitWordCuts(selectedUnitId, cuts);
    },
    [selectedUnitId, updateUnitWordCuts],
  );

  const {
    markers,
    markerMode,
    selectedMarkerId,
    setMarkers,
    toggleMarkerMode,
    addSpatialMarker,
    addTemporalMarker,
    deleteMarker,
    renameMarker,
    moveMarker,
    selectMarker,
  } = useMarkers(currentEditUnit?.markers || [], handleMarkersChange);

  useEffect(() => {
    const unitMarkers = currentEditUnit?.markers || [];
    resetMarkerCounter(unitMarkers);
    setMarkers(unitMarkers);
  }, [selectedUnitId, currentEditUnit?.markers, setMarkers]);

  const handleEndSession = useCallback(async () => {
    if (!showEndConfirm) {
      setShowEndConfirm(true);
      return;
    }
    await endSession();
    setShowEndConfirm(false);
  }, [showEndConfirm, endSession]);

  const handleDropFiles = useCallback(async (files: File[]) => {
    if (!selectedUnitId) return;
    for (const file of files) {
      try {
        const result = await uploadFile(file);
        const ext = file.name.split(".").pop()?.toLowerCase() || "";
        const videoExts = ["mp4", "mov", "mkv", "avi", "webm"];
        const audioExts = ["wav", "mp3", "aac", "flac"];
        const imageExts = ["jpg", "jpeg", "png", "webp", "gif"];
        const type = videoExts.includes(ext) ? "video"
          : audioExts.includes(ext) ? "audio"
          : imageExts.includes(ext) ? "image"
          : "other";
        addUnitMedia(selectedUnitId, {
          path: result.path,
          filename: result.filename,
          type,
        });
      } catch (err) {
        console.error("Upload failed:", err);
      }
    }
  }, [selectedUnitId, addUnitMedia]);

  // For inserted units with no footage manifest, synthesize clips from added media
  // so the existing PlayerTab pipeline (video + transcript + word cuts) works unchanged.
  const clips = useMemo(() => {
    const manifestClips = unitManifest?.clips || [];
    const media = currentEditUnit?.added_media || [];
    const syntheticClips = media
      .filter((m) => m.type === "video" || m.type === "audio")
      .map((m) => mediaToSyntheticClip(m));
    // Deduplicate: don't add synthetic clips whose IDs already exist in manifest clips
    const existingIds = new Set(manifestClips.map((c) => c.id));
    const newSynthetics = syntheticClips.filter((c) => !existingIds.has(c.id));
    return [...manifestClips, ...newSynthetics];
  }, [unitManifest, currentEditUnit?.added_media]);

  // Clip edit handlers (must be after `clips` memo)
  const activeClipEdit = selectedUnitId && activeClipId && currentEditUnit?.clip_edits
    ? currentEditUnit.clip_edits[activeClipId]
    : undefined;

  const handleSplit = useCallback(
    (time: number) => {
      if (!selectedUnitId || !activeClipId) return;
      splitClipAt(selectedUnitId, activeClipId, time);
    },
    [selectedUnitId, activeClipId, splitClipAt],
  );

  const handleRemoveSplit = useCallback(
    (index: number) => {
      if (!selectedUnitId || !activeClipId) return;
      removeSplit(selectedUnitId, activeClipId, index);
    },
    [selectedUnitId, activeClipId, removeSplit],
  );

  const handleMoveClip = useCallback(
    (clipId: string, toUnitId: string) => {
      if (!selectedUnitId) return;
      moveClipToUnit(clipId, selectedUnitId, toUnitId);
    },
    [selectedUnitId, moveClipToUnit],
  );

  useKeyboard({
    onToggleMarkerMode: toggleMarkerMode,
    onPlayPause: () => playerRef.current?.togglePlay(),
    onFrameForward: () => playerRef.current?.stepFrame(1),
    onFrameBack: () => playerRef.current?.stepFrame(-1),
    onDelete: () => {
      if (selectedMarkerId) deleteMarker(selectedMarkerId);
    },
    onShowHelp: () => setShowHelp(true),
    onSplit: () => {
      const time = playerRef.current?.getCurrentTime();
      if (time != null) handleSplit(time);
    },
  });

  if (manifestLoading || editLoading) {
    return (
      <div className="h-screen flex items-center justify-center bg-cp-bg">
        <div className="text-center">
          <div className="text-lg font-heading text-cp-primary mb-2">claudepipe studio</div>
          <div className="text-sm text-cp-text-muted">Loading project...</div>
        </div>
      </div>
    );
  }

  if (manifestError) {
    return (
      <div className="h-screen flex items-center justify-center bg-cp-bg">
        <div className="text-center max-w-md">
          <div className="text-lg font-heading text-cp-error mb-2">Failed to load manifest</div>
          <div className="text-sm text-cp-text-secondary">{manifestError}</div>
          <div className="text-xs text-cp-text-muted mt-4">
            Make sure PROJECT_ROOT points to a valid footage project with footage_manifest.json
          </div>
        </div>
      </div>
    );
  }

  if (!manifest || !editManifest) {
    return (
      <div className="h-screen flex items-center justify-center bg-cp-bg">
        <div className="text-sm text-cp-text-muted">No data loaded</div>
      </div>
    );
  }

  const units = manifest.units || [];
  const unitMap = new Map(units.map((u) => [u.unit_id, u]));
  // For inserted units (not in footage manifest), create a synthetic UnitEntry from edit manifest
  const getUnit = (id: string) => {
    const existing = unitMap.get(id);
    if (existing) return existing;
    const eu = editManifest.units[id];
    if (!eu) return null;
    return {
      unit_id: id,
      type: eu.unit_type || "video",
      display_name: eu.display_name,
      activity: "",
      clip_ids: eu.bundle_clip_ids || [],
      duration_seconds: 0,
      segment_count: 0,
    };
  };
  const selectedUnit = selectedUnitId ? getUnit(selectedUnitId) : null;
  const editUnit = selectedUnitId ? editManifest.units[selectedUnitId] || null : null;
  const claudeNote = selectedUnitId ? editManifest.claude_notes[selectedUnitId] || null : null;

  return (
    <>
      <AppShell
        saving={saving}
        markerMode={markerMode}
        onEndSession={handleEndSession}
        onToggleMarkerMode={toggleMarkerMode}
        sidebar={
          <Sidebar
            units={units}
            editManifest={editManifest}
            selectedUnitId={selectedUnitId}
            onSelectUnit={setSelectedUnitId}
            onReorder={updateUnitOrder}
            onInsertUnit={insertUnit}
            onDeleteUnit={deleteUnit}
          />
        }
        main={
          <MainPanel
            unitManifest={unitManifest}
            unitManifestLoading={unitManifestLoading}
            unitManifestError={unitManifestError}
            selectedUnit={selectedUnit}
            editUnit={editUnit}
            claudeNote={claudeNote}
            selectedUnitId={selectedUnitId}
            clips={clips}
            activeClipId={activeClipId}
            onClipChange={setActiveClipId}
            markers={markers}
            markerMode={markerMode}
            selectedMarkerId={selectedMarkerId}
            wordCuts={currentEditUnit?.word_cuts || []}
            onWordCutsChange={handleWordCutsChange}
            addedMedia={currentEditUnit?.added_media || []}
            onRemoveMedia={(index: number) => {
              if (selectedUnitId) removeUnitMedia(selectedUnitId, index);
            }}
            discardedClips={currentEditUnit?.discarded_clips || []}
            onToggleDiscardClip={(clipId) => {
              if (selectedUnitId) toggleDiscardClip(selectedUnitId, clipId);
            }}
            onAddSpatialMarker={addSpatialMarker}
            onAddTemporalMarker={addTemporalMarker}
            onSelectMarker={selectMarker}
            onMoveMarker={moveMarker}
            onRenameMarker={renameMarker}
            onDeleteMarker={deleteMarker}
            clipEdit={activeClipEdit}
            onInstructionsChange={updateUnitInstructions}
            onDropFiles={handleDropFiles}
            onPlayClip={(clipId) => setActiveClipId(clipId)}
            onSplit={handleSplit}
            onRemoveSplit={handleRemoveSplit}
            onMoveClip={handleMoveClip}
            availableUnits={editManifest.unit_order
              .filter((id) => id !== selectedUnitId)
              .map((id) => ({
                id,
                name: editManifest.units[id]?.display_name || id,
              }))}
            playerRef={playerRef}
          />
        }
        statusBar={
          <StatusBar
            saving={saving}
            error={editError}
            unitCount={editManifest.unit_order.length}
            markerMode={markerMode}
          />
        }
      />

      {showEndConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-cp-bg-elevated border border-cp-border rounded-lg p-5 max-w-sm">
            <h2 className="text-lg font-heading font-semibold mb-2">End Session?</h2>
            <p className="text-sm text-cp-text-secondary mb-4">
              This will save all changes and mark the session as complete. Claude will then process your instructions.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowEndConfirm(false)}
                className="px-4 py-1.5 text-sm rounded border border-cp-border hover:bg-cp-bg-surface"
              >
                Cancel
              </button>
              <button
                onClick={handleEndSession}
                className="px-4 py-1.5 text-sm rounded bg-cp-error hover:bg-cp-error/80"
              >
                End Session
              </button>
            </div>
          </div>
        </div>
      )}

      {showHelp && <KeyboardHelp onClose={() => setShowHelp(false)} />}
    </>
  );
}
