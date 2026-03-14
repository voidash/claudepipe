import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { LogOut, Crosshair, Loader2 } from "lucide-react";
import { cn } from "../../lib/cn";

interface AppShellProps {
  saving: boolean;
  markerMode: boolean;
  onEndSession: () => void;
  onToggleMarkerMode: () => void;
  sidebar: React.ReactNode;
  main: React.ReactNode;
  statusBar: React.ReactNode;
}

export function AppShell({
  saving,
  markerMode,
  onEndSession,
  onToggleMarkerMode,
  sidebar,
  main,
  statusBar,
}: AppShellProps) {
  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <div className="h-10 flex items-center justify-between px-4 border-b border-cp-border bg-cp-bg-elevated shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="text-sm font-heading font-bold">
            <span className="text-cp-primary">claudepipe</span>{" "}
            <span className="text-cp-text-secondary">studio</span>
          </h1>
          {saving && (
            <span className="flex items-center gap-1 text-xs text-cp-text-muted">
              <Loader2 className="w-3 h-3 animate-spin" />
              Saving...
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onToggleMarkerMode}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1 text-xs rounded transition-colors",
              markerMode
                ? "bg-cp-accent/20 text-cp-accent border border-cp-accent/40"
                : "text-cp-text-muted hover:text-cp-text hover:bg-cp-bg-surface",
            )}
            title="Toggle marker mode (M)"
          >
            <Crosshair className="w-3.5 h-3.5" />
            Markers
          </button>

          <button
            onClick={onEndSession}
            className="flex items-center gap-1.5 px-3 py-1 text-xs rounded text-cp-error hover:bg-cp-error/10 transition-colors"
            title="End session"
          >
            <LogOut className="w-3.5 h-3.5" />
            End Session
          </button>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 min-h-0">
        <PanelGroup direction="horizontal">
          <Panel defaultSize={20} minSize={15} maxSize={40}>
            {sidebar}
          </Panel>
          <PanelResizeHandle className="w-1 bg-cp-border hover:bg-cp-primary transition-colors cursor-col-resize" />
          <Panel defaultSize={80} minSize={50}>
            {main}
          </Panel>
        </PanelGroup>
      </div>

      {/* Status bar */}
      {statusBar}
    </div>
  );
}
