import { useEffect, useCallback } from "react";

interface KeyboardShortcuts {
  onToggleMarkerMode?: () => void;
  onPlayPause?: () => void;
  onFrameForward?: () => void;
  onFrameBack?: () => void;
  onDelete?: () => void;
  onShowHelp?: () => void;
  onSplit?: () => void;
}

export function useKeyboard(shortcuts: KeyboardShortcuts): void {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      // Don't intercept when typing in inputs
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" ||
        target.isContentEditable
      ) {
        return;
      }

      switch (e.key) {
        case "m":
        case "M":
          e.preventDefault();
          shortcuts.onToggleMarkerMode?.();
          break;
        case " ":
          e.preventDefault();
          shortcuts.onPlayPause?.();
          break;
        case "ArrowRight":
          e.preventDefault();
          shortcuts.onFrameForward?.();
          break;
        case "ArrowLeft":
          e.preventDefault();
          shortcuts.onFrameBack?.();
          break;
        case "s":
          if (e.metaKey || e.ctrlKey) {
            // Ctrl+S / Cmd+S — no-op, all changes auto-save
            e.preventDefault();
          } else {
            e.preventDefault();
            shortcuts.onSplit?.();
          }
          break;
        case "Delete":
        case "Backspace":
          shortcuts.onDelete?.();
          break;
        case "?":
          e.preventDefault();
          shortcuts.onShowHelp?.();
          break;
      }
    },
    [shortcuts],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);
}
