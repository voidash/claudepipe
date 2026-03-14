import type { Marker } from "../types/edit-manifest";

let markerCounter = 0;

export function resetMarkerCounter(existingMarkers: Marker[]): void {
  const maxNum = existingMarkers.reduce((max, m) => {
    const match = m.id.match(/^m(\d+)$/);
    return match ? Math.max(max, parseInt(match[1], 10)) : max;
  }, 0);
  markerCounter = maxNum;
}

export function nextMarkerId(): string {
  markerCounter++;
  return `m${markerCounter}`;
}

export function createSpatialMarker(
  time: number,
  frameNumber: number,
  x: number,
  y: number,
  clipId: string,
): Marker {
  const id = nextMarkerId();
  return {
    id,
    name: id,
    time,
    frame_number: frameNumber,
    position: { x, y },
    type: "spatial",
    source_clip_id: clipId,
  };
}

export function createTemporalMarker(
  time: number,
  frameNumber: number,
  clipId: string,
): Marker {
  const id = nextMarkerId();
  return {
    id,
    name: id,
    time,
    frame_number: frameNumber,
    position: null,
    type: "temporal",
    source_clip_id: clipId,
  };
}
