export function timeToFrame(time: number, fps: number): number {
  return Math.round(time * fps);
}

export function frameToTime(frame: number, fps: number): number {
  return frame / fps;
}

export function formatFrameTimecode(time: number, fps: number): string {
  const totalFrames = Math.round(time * fps);
  const h = Math.floor(totalFrames / (fps * 3600));
  const m = Math.floor((totalFrames % (fps * 3600)) / (fps * 60));
  const s = Math.floor((totalFrames % (fps * 60)) / fps);
  const f = totalFrames % Math.round(fps);

  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}:${String(f).padStart(2, "0")}`;
}
