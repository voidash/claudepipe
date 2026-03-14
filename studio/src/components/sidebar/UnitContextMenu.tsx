import { useEffect, useRef } from "react";
import { Plus, Trash2 } from "lucide-react";

interface ContextMenuPosition {
  x: number;
  y: number;
  unitId: string;
  index: number;
}

interface UnitContextMenuProps {
  position: ContextMenuPosition;
  onClose: () => void;
  onInsertBefore: () => void;
  onInsertAfter: () => void;
  onDelete: () => void;
}

export function UnitContextMenu({
  position,
  onClose,
  onInsertBefore,
  onInsertAfter,
  onDelete,
}: UnitContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="fixed z-50 bg-cp-bg-elevated border border-cp-border rounded-md shadow-lg py-1 min-w-[180px]"
      style={{ left: position.x, top: position.y }}
    >
      <button
        className="w-full flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-cp-bg-surface text-left"
        onClick={() => { onInsertBefore(); onClose(); }}
      >
        <Plus className="w-3.5 h-3.5" />
        Insert before
      </button>
      <button
        className="w-full flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-cp-bg-surface text-left"
        onClick={() => { onInsertAfter(); onClose(); }}
      >
        <Plus className="w-3.5 h-3.5" />
        Insert after
      </button>
      <div className="border-t border-cp-border my-1" />
      <button
        className="w-full flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-cp-bg-surface text-left text-cp-error"
        onClick={() => { onDelete(); onClose(); }}
      >
        <Trash2 className="w-3.5 h-3.5" />
        Delete unit
      </button>
    </div>
  );
}
