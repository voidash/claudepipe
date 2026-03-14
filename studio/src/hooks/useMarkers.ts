import { useState, useCallback } from "react";
import type { Marker } from "../types/edit-manifest";
import { createSpatialMarker, createTemporalMarker, resetMarkerCounter } from "../lib/marker-utils";

interface UseMarkersResult {
  markers: Marker[];
  markerMode: boolean;
  selectedMarkerId: string | null;
  setMarkers: (markers: Marker[]) => void;
  toggleMarkerMode: () => void;
  addSpatialMarker: (time: number, frameNumber: number, x: number, y: number, clipId: string) => void;
  addTemporalMarker: (time: number, frameNumber: number, clipId: string) => void;
  deleteMarker: (id: string) => void;
  renameMarker: (id: string, name: string) => void;
  moveMarker: (id: string, x: number, y: number) => void;
  selectMarker: (id: string | null) => void;
}

export function useMarkers(
  initialMarkers: Marker[],
  onMarkersChange: (markers: Marker[]) => void,
): UseMarkersResult {
  const [markers, setMarkersState] = useState<Marker[]>(initialMarkers);
  const [markerMode, setMarkerMode] = useState(false);
  const [selectedMarkerId, setSelectedMarkerId] = useState<string | null>(null);

  const setMarkers = useCallback((newMarkers: Marker[]) => {
    resetMarkerCounter(newMarkers);
    setMarkersState(newMarkers);
    onMarkersChange(newMarkers);
  }, [onMarkersChange]);

  const toggleMarkerMode = useCallback(() => {
    setMarkerMode((prev) => !prev);
  }, []);

  const addSpatialMarker = useCallback(
    (time: number, frameNumber: number, x: number, y: number, clipId: string) => {
      const marker = createSpatialMarker(time, frameNumber, x, y, clipId);
      const next = [...markers, marker];
      setMarkersState(next);
      onMarkersChange(next);
      setSelectedMarkerId(marker.id);
    },
    [markers, onMarkersChange],
  );

  const addTemporalMarker = useCallback(
    (time: number, frameNumber: number, clipId: string) => {
      const marker = createTemporalMarker(time, frameNumber, clipId);
      const next = [...markers, marker];
      setMarkersState(next);
      onMarkersChange(next);
      setSelectedMarkerId(marker.id);
    },
    [markers, onMarkersChange],
  );

  const deleteMarker = useCallback(
    (id: string) => {
      const next = markers.filter((m) => m.id !== id);
      setMarkersState(next);
      onMarkersChange(next);
      if (selectedMarkerId === id) setSelectedMarkerId(null);
    },
    [markers, onMarkersChange, selectedMarkerId],
  );

  const renameMarker = useCallback(
    (id: string, name: string) => {
      const next = markers.map((m) => (m.id === id ? { ...m, name } : m));
      setMarkersState(next);
      onMarkersChange(next);
    },
    [markers, onMarkersChange],
  );

  const moveMarker = useCallback(
    (id: string, x: number, y: number) => {
      const next = markers.map((m) =>
        m.id === id ? { ...m, position: { x, y } } : m,
      );
      setMarkersState(next);
      onMarkersChange(next);
    },
    [markers, onMarkersChange],
  );

  const selectMarker = useCallback((id: string | null) => {
    setSelectedMarkerId(id);
  }, []);

  return {
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
  };
}
