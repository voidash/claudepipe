import { useState, useCallback } from "react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import type { UnitEntry } from "../../types/manifest";
import type { EditManifest } from "../../types/edit-manifest";
import { UnitCard } from "../sidebar/UnitCard";
import { UnitContextMenu } from "../sidebar/UnitContextMenu";
import { InsertUnitDialog } from "../sidebar/InsertUnitDialog";

interface SidebarProps {
  units: UnitEntry[];
  editManifest: EditManifest;
  selectedUnitId: string | null;
  onSelectUnit: (unitId: string) => void;
  onReorder: (order: string[]) => void;
  onInsertUnit: (unitId: string, unit: any, afterIndex: number) => void;
  onDeleteUnit: (unitId: string) => void;
}

export function Sidebar({
  units,
  editManifest,
  selectedUnitId,
  onSelectUnit,
  onReorder,
  onInsertUnit,
  onDeleteUnit,
}: SidebarProps) {
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    unitId: string;
    index: number;
  } | null>(null);
  const [insertDialog, setInsertDialog] = useState<{
    open: boolean;
    afterIndex: number;
  }>({ open: false, afterIndex: -1 });

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const unitOrder = editManifest.unit_order;
  const unitMap = new Map(units.map((u) => [u.unit_id, u]));

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;

      const oldIndex = unitOrder.indexOf(active.id as string);
      const newIndex = unitOrder.indexOf(over.id as string);
      if (oldIndex === -1 || newIndex === -1) return;

      const newOrder = [...unitOrder];
      newOrder.splice(oldIndex, 1);
      newOrder.splice(newIndex, 0, active.id as string);
      onReorder(newOrder);
    },
    [unitOrder, onReorder],
  );

  const handleContextMenu = useCallback(
    (e: React.MouseEvent, unitId: string, index: number) => {
      e.preventDefault();
      setContextMenu({ x: e.clientX, y: e.clientY, unitId, index });
    },
    [],
  );

  return (
    <div className="h-full flex flex-col bg-cp-bg">
      <div className="px-3 py-2 border-b border-cp-border">
        <h2 className="text-sm font-heading font-semibold text-cp-text-secondary">Units</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContext items={unitOrder} strategy={verticalListSortingStrategy}>
            {unitOrder.map((unitId, index) => {
              const editUnit = editManifest.units[unitId];
              const unit = unitMap.get(unitId) || (editUnit ? {
                unit_id: unitId,
                type: editUnit.unit_type || "video",
                display_name: editUnit.display_name,
                activity: "",
                clip_ids: editUnit.bundle_clip_ids || [],
                duration_seconds: 0,
                segment_count: 0,
              } : null);
              if (!unit) return null;
              return (
                <UnitCard
                  key={unitId}
                  unitId={unitId}
                  unit={unit}
                  editUnit={editUnit}
                  selected={selectedUnitId === unitId}
                  onClick={() => onSelectUnit(unitId)}
                  onContextMenu={(e) => handleContextMenu(e, unitId, index)}
                />
              );
            })}
          </SortableContext>
        </DndContext>
      </div>

      {contextMenu && (
        <UnitContextMenu
          position={contextMenu}
          onClose={() => setContextMenu(null)}
          onInsertBefore={() =>
            setInsertDialog({ open: true, afterIndex: contextMenu.index - 1 })
          }
          onInsertAfter={() =>
            setInsertDialog({ open: true, afterIndex: contextMenu.index })
          }
          onDelete={() => onDeleteUnit(contextMenu.unitId)}
        />
      )}

      <InsertUnitDialog
        open={insertDialog.open}
        onClose={() => setInsertDialog({ open: false, afterIndex: -1 })}
        onInsert={(unitId, unit) => onInsertUnit(unitId, unit, insertDialog.afterIndex)}
        afterIndex={insertDialog.afterIndex}
      />
    </div>
  );
}
