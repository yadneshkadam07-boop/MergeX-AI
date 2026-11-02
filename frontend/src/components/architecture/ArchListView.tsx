import { useState } from "react";
import type { ArchNode, ArchEdge } from "@/types/architecture";
import type { Issue } from "@/types/issue";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ChevronDown, ChevronUp, ArrowRight, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";

interface ArchListViewProps {
  nodes: ArchNode[];
  edges: ArchEdge[];
  issues: Issue[];
  onSelectIssue: (issueId: string) => void;
}

export function ArchListView({ nodes, edges, issues, onSelectIssue }: ArchListViewProps) {
  const [expanded, setExpanded] = useState(false);

  const getNodeLabel = (nodeId: string) => {
    return nodes.find((n) => n.id === nodeId)?.label || nodeId;
  };

  const getEdgeAttachedIssues = (edge: ArchEdge) => {
    if (!edge.issueIds || edge.issueIds.length === 0) return [];
    return issues.filter((i) => edge.issueIds?.includes(i.id) && i.status === "open");
  };

  return (
    <div className="bg-card/60 rounded-xl border p-4 shadow-2xs">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="text-muted-foreground text-xs font-semibold tracking-wider uppercase">
            Accessible Text Alternative
          </h4>
          <p className="text-foreground mt-0.5 text-xs">
            Full connection topology and interface contract summary.
          </p>
        </div>

        <Button
          variant="outline"
          size="sm"
          onClick={() => setExpanded(!expanded)}
          className="h-8 gap-1.5 text-xs font-medium"
          aria-expanded={expanded}
        >
          <span>{expanded ? "Hide List View" : "View as List"}</span>
          {expanded ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
        </Button>
      </div>

      {expanded && (
        <div className="animate-in fade-in-0 mt-4 space-y-3 border-t pt-3 duration-200">
          <ul className="divide-border/60 divide-y text-xs">
            {edges.map((edge) => {
              const sourceLabel = getNodeLabel(edge.source);
              const targetLabel = getNodeLabel(edge.target);
              const edgeIssues = getEdgeAttachedIssues(edge);

              return (
                <li key={edge.id} className="space-y-1.5 py-2.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-foreground flex items-center gap-2 font-medium">
                      <span>{sourceLabel}</span>
                      <ArrowRight className="text-muted-foreground size-3.5" />
                      <span>{targetLabel}</span>
                      <span className="text-muted-foreground font-mono">({edge.label})</span>
                    </div>

                    <Badge
                      variant="outline"
                      className={cn(
                        "text-[10px] font-semibold uppercase",
                        edge.status === "broken"
                          ? "border-sev-critical bg-sev-critical/12 text-sev-critical"
                          : edge.status === "warning"
                            ? "border-sev-medium bg-sev-medium/12 text-sev-medium"
                            : "border-success bg-success/12 text-success",
                      )}
                    >
                      {edge.status}: {edgeIssues.length} issue{edgeIssues.length === 1 ? "" : "s"}
                    </Badge>
                  </div>

                  {edgeIssues.length > 0 && (
                    <div className="space-y-1 pl-4">
                      {edgeIssues.map((iss) => (
                        <button
                          key={iss.id}
                          type="button"
                          onClick={() => onSelectIssue(iss.id)}
                          className="text-primary flex cursor-pointer items-center gap-1.5 text-left text-xs hover:underline"
                        >
                          <ShieldAlert className="text-sev-medium size-3" />
                          <span>
                            {iss.title} ({iss.filePath})
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
