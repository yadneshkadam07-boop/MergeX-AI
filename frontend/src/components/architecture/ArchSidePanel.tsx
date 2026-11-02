import { useSearchParams } from "react-router-dom";
import type { ArchNode, ArchEdge } from "@/types/architecture";
import type { Issue } from "@/types/issue";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ChevronRight, X } from "lucide-react";

interface ArchSidePanelProps {
  selectedItem: { type: "node"; data: ArchNode } | { type: "edge"; data: ArchEdge } | null;
  attachedIssues: Issue[];
  onClose: () => void;
}

export function ArchSidePanel({ selectedItem, attachedIssues, onClose }: ArchSidePanelProps) {
  const [searchParams, setSearchParams] = useSearchParams();

  if (!selectedItem) return null;

  const isNode = selectedItem.type === "node";
  const node = selectedItem.type === "node" ? selectedItem.data : null;
  const edge = selectedItem.type === "edge" ? selectedItem.data : null;

  const handleOpenIssue = (issueId: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("issue", issueId);
    setSearchParams(next, { replace: true });
  };

  const content = (
    <div className="space-y-4">
      {/* Title & Status */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Badge variant="outline" className="font-mono text-xs uppercase">
            {isNode ? `Component: ${node?.kind}` : "Connection Pipeline"}
          </Badge>
          {!isNode && edge && (
            <Badge
              variant="outline"
              className={
                edge.status === "broken"
                  ? "border-sev-critical bg-sev-critical/12 text-sev-critical font-semibold"
                  : edge.status === "warning"
                    ? "border-sev-medium bg-sev-medium/12 text-sev-medium font-semibold"
                    : "border-success bg-success/12 text-success font-semibold"
              }
            >
              {edge.status.toUpperCase()}
            </Badge>
          )}
        </div>

        <h3 className="text-foreground text-lg font-bold">{isNode ? node?.label : edge?.label}</h3>

        {isNode && node && (
          <p className="text-muted-foreground bg-muted/50 rounded p-2 font-mono text-xs">
            Stack: <strong className="text-foreground">{node.tech}</strong>
          </p>
        )}

        <p className="text-muted-foreground text-xs leading-relaxed">
          {isNode
            ? node?.description
            : `Transmits payload requests between source component (${edge?.source}) and destination (${edge?.target}).`}
        </p>
      </div>

      {/* Attached Open Issues */}
      <div className="space-y-2.5 border-t pt-2">
        <div className="flex items-center justify-between text-xs font-semibold">
          <span>Attached Open Issues</span>
          <span className="text-muted-foreground font-mono">
            {attachedIssues.length} item{attachedIssues.length === 1 ? "" : "s"}
          </span>
        </div>

        {attachedIssues.length === 0 ? (
          <p className="text-muted-foreground bg-muted/20 rounded-lg p-3 text-center text-xs italic">
            Zero active open issues flagged on this element.
          </p>
        ) : (
          <div className="space-y-2">
            {attachedIssues.map((issue) => (
              <div
                key={issue.id}
                role="button"
                tabIndex={0}
                onClick={() => handleOpenIssue(issue.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    handleOpenIssue(issue.id);
                  }
                }}
                className="bg-background hover:bg-muted/40 focus-visible:ring-ring flex cursor-pointer items-start justify-between gap-2 rounded-lg border p-2.5 text-left transition-colors focus:outline-hidden focus-visible:ring-2"
              >
                <div className="min-w-0 space-y-1">
                  <div className="flex items-center gap-1.5">
                    <SeverityBadge severity={issue.severity} />
                    <span className="text-foreground truncate text-xs font-semibold">
                      {issue.title}
                    </span>
                  </div>
                  <p className="text-muted-foreground truncate text-[11px]">{issue.filePath}</p>
                </div>
                <ChevronRight className="text-muted-foreground mt-0.5 size-4 shrink-0" />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop side card overlay */}
      <Card className="bg-card/95 animate-in fade-in-0 slide-in-from-right-4 absolute top-4 right-4 z-10 hidden w-80 border shadow-xl backdrop-blur-md duration-200 lg:block">
        <CardHeader className="flex flex-row items-center justify-between border-b p-4 pb-2">
          <CardTitle className="text-muted-foreground text-xs font-semibold tracking-wider uppercase">
            Element Inspector
          </CardTitle>
          <Button variant="ghost" size="icon" className="size-7" onClick={onClose}>
            <X className="size-4" />
          </Button>
        </CardHeader>
        <CardContent className="p-4">{content}</CardContent>
      </Card>

      {/* Mobile bottom sheet drawer */}
      <div className="lg:hidden">
        <Sheet open={Boolean(selectedItem)} onOpenChange={(open) => !open && onClose()}>
          <SheetContent side="bottom" className="max-h-[80vh] overflow-y-auto p-6">
            <SheetHeader className="pb-2 text-left">
              <SheetTitle className="text-base font-bold">Element Inspector</SheetTitle>
              <SheetDescription className="text-xs">
                Topology node and connection diagnostics.
              </SheetDescription>
            </SheetHeader>
            {content}
          </SheetContent>
        </Sheet>
      </div>
    </>
  );
}
