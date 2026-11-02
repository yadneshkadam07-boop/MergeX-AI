import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { ArchNodeKind } from "@/types/architecture";
import { Badge } from "@/components/ui/badge";
import { Cloud, Cpu, Database, Globe, Key, Server } from "lucide-react";
import { cn } from "@/lib/utils";

export interface CustomNodeData {
  label: string;
  kind: ArchNodeKind;
  tech: string;
  description: string;
  issueIds: string[];
  isDimmed?: boolean;
  hasCriticalOrHigh?: boolean;
  hasMedium?: boolean;
}

function ArchCustomNodeComponent({ data, selected }: NodeProps) {
  const nodeData = data as unknown as CustomNodeData;

  const renderIcon = (kind: ArchNodeKind) => {
    const iconClass = "size-4 text-primary shrink-0";
    switch (kind) {
      case "frontend":
        return <Globe className={iconClass} />;
      case "api":
        return <Server className={iconClass} />;
      case "database":
        return <Database className={iconClass} />;
      case "auth":
        return <Key className={iconClass} />;
      case "worker":
        return <Cpu className={iconClass} />;
      case "external":
        return <Cloud className={iconClass} />;
    }
  };

  const issueCount = nodeData.issueIds?.length || 0;

  // Ring styling according to issue severity using severity tokens
  let ringClasses = "border-border";
  if (nodeData.hasCriticalOrHigh) {
    ringClasses = "border-sev-critical ring-2 ring-sev-critical/30";
  } else if (nodeData.hasMedium) {
    ringClasses = "border-sev-medium ring-2 ring-sev-medium/30";
  }

  return (
    <div
      className={cn(
        "bg-card relative w-56 cursor-pointer rounded-xl border p-3 text-left shadow-md transition-all duration-200 select-none",
        ringClasses,
        selected && "ring-primary border-primary ring-2",
        nodeData.isDimmed && "opacity-25 grayscale-[60%]",
      )}
    >
      {/* React Flow Handles */}
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-primary border-background !size-2 border-2"
      />

      <div className="space-y-2">
        {/* Header: Icon, Label, and Issue Count Badge */}
        <div className="flex items-center justify-between gap-1.5">
          <div className="flex min-w-0 items-center gap-1.5">
            <div className="bg-primary/10 flex size-7 items-center justify-center rounded-lg">
              {renderIcon(nodeData.kind)}
            </div>
            <span className="text-foreground truncate text-xs font-semibold">{nodeData.label}</span>
          </div>

          {issueCount > 0 && (
            <Badge
              variant="outline"
              className={cn(
                "shrink-0 px-1.5 py-0 font-mono text-[10px] font-bold",
                nodeData.hasCriticalOrHigh
                  ? "border-sev-critical bg-sev-critical/12 text-sev-critical"
                  : "border-sev-medium bg-sev-medium/12 text-sev-medium",
              )}
            >
              {issueCount} issue{issueCount === 1 ? "" : "s"}
            </Badge>
          )}
        </div>

        {/* Tech chip */}
        <div className="flex items-center justify-between border-t pt-1.5 text-[11px]">
          <span className="text-muted-foreground max-w-[130px] truncate font-mono">
            {nodeData.tech}
          </span>
          <span className="text-muted-foreground/70 text-[10px] font-semibold uppercase">
            {nodeData.kind}
          </span>
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Right}
        className="!bg-primary border-background !size-2 border-2"
      />
    </div>
  );
}

export const ArchCustomNode = memo(ArchCustomNodeComponent);
