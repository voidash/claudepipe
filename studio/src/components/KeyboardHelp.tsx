import { useEffect } from "react";

interface KeyboardHelpProps {
  onClose: () => void;
}

const shortcuts = [
  { key: "Space", description: "Play / Pause" },
  { key: "\u2190", description: "Previous frame" },
  { key: "\u2192", description: "Next frame" },
  { key: "M", description: "Toggle marker mode" },
  { key: "S", description: "Split at playhead" },
  { key: "Del", description: "Delete selected marker" },
  { key: "?", description: "Show this help" },
];

export function KeyboardHelp({ onClose }: KeyboardHelpProps) {
  useEffect(() => {
    const handle = (e: KeyboardEvent) => {
      e.preventDefault();
      onClose();
    };
    // Close on any key after a brief delay to avoid immediate re-trigger
    const timer = setTimeout(() => {
      window.addEventListener("keydown", handle);
    }, 100);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("keydown", handle);
    };
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
    >
      <div
        className="bg-cp-bg-elevated border border-cp-border rounded-lg p-5 max-w-sm w-full"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-heading font-semibold mb-4">
          Keyboard Shortcuts
        </h2>
        <div className="space-y-2">
          {shortcuts.map((s) => (
            <div key={s.key} className="flex items-center justify-between">
              <span className="text-sm text-cp-text-secondary">
                {s.description}
              </span>
              <kbd className="px-2 py-0.5 text-xs bg-cp-bg-surface border border-cp-border rounded font-code">
                {s.key}
              </kbd>
            </div>
          ))}
        </div>
        <div className="mt-4 text-center text-xs text-cp-text-muted">
          Press any key or click outside to close
        </div>
      </div>
    </div>
  );
}
