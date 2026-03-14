import { useState, useCallback } from "react";
import { Upload } from "lucide-react";
import { cn } from "../../lib/cn";

interface DropZoneProps {
  onDropPaths: (paths: string[]) => void;
}

export function DropZone({ onDropPaths }: DropZoneProps) {
  const [dragOver, setDragOver] = useState(false);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragOver(false);

      // In Electron or when dragging from OS file manager, we might get file paths
      // In a pure browser context, we get File objects
      // Since this is a local tool, we'll handle both cases

      const items = e.dataTransfer.items;
      const paths: string[] = [];

      if (items) {
        for (let i = 0; i < items.length; i++) {
          const item = items[i];
          // Try to get file path from the item
          if (item.kind === "file") {
            const file = item.getAsFile();
            if (file) {
              // In browser, File.path is not available (security restriction)
              // But the file name can help the user
              // For now, we collect what we can
              paths.push(file.name);
            }
          }
        }
      }

      // If we got paths through DataTransfer (OS-level drag)
      const text = e.dataTransfer.getData("text/plain");
      if (text) {
        // Could be newline-separated file paths
        const textPaths = text.split("\n").map((p) => p.trim()).filter(Boolean);
        paths.push(...textPaths);
      }

      if (paths.length > 0) {
        onDropPaths(paths);
      }
    },
    [onDropPaths],
  );

  return (
    <div
      className={cn(
        "border-2 border-dashed rounded-lg p-8 text-center transition-all cursor-pointer",
        dragOver
          ? "border-cp-primary bg-cp-primary/5"
          : "border-cp-border hover:border-cp-text-muted",
      )}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <Upload
        className={cn(
          "w-8 h-8 mx-auto mb-3",
          dragOver ? "text-cp-primary" : "text-cp-text-muted",
        )}
      />
      <p className="text-sm text-cp-text-secondary mb-1">
        Drag & drop files here
      </p>
      <p className="text-xs text-cp-text-muted">
        Video, audio, images, or text files
      </p>
    </div>
  );
}
