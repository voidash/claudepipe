import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Video, Monitor, Mic, Type, Sparkles, FileVideo } from "lucide-react";
import type { UnitEntry } from "../../types/manifest";
import type { EditUnit } from "../../types/edit-manifest";
import { formatTimecode } from "../../lib/manifest-utils";
import { cn } from "../../lib/cn";

const iconMap: Record<string, React.ComponentType<{ className?: string }>> = {
  video: Video,
  screencast: Monitor,
  audio: Mic,
  text_image: Type,
  animation: Sparkles,
};

interface UnitCardProps {
  unitId: string;
  unit: UnitEntry;
  editUnit?: EditUnit;
  selected: boolean;
  onClick: () => void;
  onContextMenu: (e: React.MouseEvent) => void;
}

export function UnitCard({
  unitId,
  unit,
  editUnit,
  selected,
  onClick,
  onContextMenu,
}: UnitCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: unitId });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const Icon = iconMap[unit.type] || FileVideo;
  const displayName = editUnit?.display_name || unit.display_name;
  const markerCount = editUnit?.markers?.length || 0;
  const hasInstructions = Boolean(editUnit?.instructions);

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "group flex items-center gap-2 px-2 py-2 rounded-md cursor-pointer transition-colors",
        "hover:bg-cp-bg-surface",
        selected && "bg-cp-bg-surface border border-cp-border-active",
        isDragging && "opacity-50",
      )}
      onClick={onClick}
      onContextMenu={onContextMenu}
    >
      <button
        className="cursor-grab active:cursor-grabbing text-cp-text-muted hover:text-cp-text p-0.5"
        {...attributes}
        {...listeners}
      >
        <GripVertical className="w-3.5 h-3.5" />
      </button>

      <Icon className="w-4 h-4 text-cp-text-secondary shrink-0" />

      <div className="flex-1 min-w-0">
        <div className="text-sm truncate">{displayName}</div>
        <div className="text-xs text-cp-text-muted flex items-center gap-2">
          <span>{formatTimecode(unit.duration_seconds)}</span>
          {markerCount > 0 && (
            <span className="text-cp-accent">{markerCount}m</span>
          )}
          {hasInstructions && (
            <span className="text-cp-primary">instr</span>
          )}
        </div>
      </div>

      <div
        className={cn(
          "w-2 h-2 rounded-full shrink-0",
          editUnit?.status === "approved" && "bg-cp-success",
          editUnit?.status === "reviewing" && "bg-cp-warning",
          editUnit?.status === "draft" && "bg-cp-text-muted",
        )}
      />
    </div>
  );
}
