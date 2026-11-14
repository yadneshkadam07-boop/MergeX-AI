import { useEffect, useState, useMemo, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ReactFlow,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  MarkerType,
  type Node,
  type Edge,
  type NodeMouseHandler,
  type EdgeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useProject } from "@/hooks/use-project";
import type { ArchNode, ArchEdge } from "@/types/architecture";
import type { Issue } from "@/types/issue";
import { getArchitecture, getIssues } from "@/lib/api";
import { ArchCustomNode, type CustomNodeData } from "@/components/architecture/ArchCustomNode";
import { ArchSidePanel } from "@/components/architecture/ArchSidePanel";
import { ArchListView } from "@/components/architecture/ArchListView";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { useThemeColors } from "@/hooks/use-theme-colors";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { GitFork, Info, Layers, AlertTriangle, CheckCircle2, XCircle } from "lucide-react";

const nodeTypes = {
  custom: ArchCustomNode,
};

export function ProjectArchitecture() {
  const { project } = useProject();
  const themeColors = useThemeColors();
  useDocumentTitle("Architecture", project.name);
  const [archData, setArchData] = useState<{ nodes: ArchNode[]; edges: ArchEdge[] }>({
    nodes: [],
    edges: [],
  });
  const [issues, setIssues] = useState<Issue[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [onlyProblems, setOnlyProblems] = useState(false);
  const [selectedItem, setSelectedItem] = useState<
    { type: "node"; data: ArchNode } | { type: "edge"; data: ArchEdge } | null
  >(null);

  const [searchParams, setSearchParams] = useSearchParams();

  // Load topology and issues
  const loadArch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [arch, issueList] = await Promise.all([
        getArchitecture(project.id),
        getIssues(project.id),
      ]);
      setArchData(arch);
      setIssues(issueList);
    } catch (err) {
      console.error("Failed to load architecture graph:", err);
      setError(err instanceof Error ? err.message : "Failed to load architecture topology.");
    } finally {
      setLoading(false);
    }
  }, [project.id]);

  useEffect(() => {
    void loadArch();
  }, [loadArch]);

  // Open issues map
  const openIssues = useMemo(() => issues.filter((i) => i.status === "open"), [issues]);

  // Prepare ReactFlow Nodes
  const flowNodes: Node[] = useMemo(() => {
    return archData.nodes.map((node) => {
      const attachedOpen = openIssues.filter((i) => node.issueIds.includes(i.id));
      const hasCriticalOrHigh = attachedOpen.some(
        (i) => i.severity === "critical" || i.severity === "high",
      );
      const hasMedium = attachedOpen.some((i) => i.severity === "medium");
      const hasProblems = attachedOpen.length > 0;

      const customData: CustomNodeData = {
        label: node.label,
        kind: node.kind,
        tech: node.tech,
        description: node.description,
        issueIds: attachedOpen.map((i) => i.id),
        isDimmed: onlyProblems && !hasProblems,
        hasCriticalOrHigh,
        hasMedium,
      };

      return {
        id: node.id,
        type: "custom",
        position: node.position || { x: 100, y: 100 },
        data: customData as unknown as Record<string, unknown>,
      };
    });
  }, [archData.nodes, openIssues, onlyProblems]);

  // Prepare ReactFlow Edges
  const flowEdges: Edge[] = useMemo(() => {
    return archData.edges.map((edge) => {
      const isBroken = edge.status === "broken";
      const isWarning = edge.status === "warning";
      const hasProblems = isBroken || isWarning;

      // Robust high-contrast stroke color ensuring solid rendering in SVG
      let strokeColor = "#10b981"; // Healthy emerald
      if (isBroken) strokeColor = "#ef4444"; // Critical red
      else if (isWarning) strokeColor = "#f59e0b"; // Medium amber

      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: "source",
        targetHandle: "target",
        label: edge.label,
        type: "smoothstep",
        animated: isBroken,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: strokeColor,
          width: 14,
          height: 14,
        },
        style: {
          stroke: strokeColor,
          strokeWidth: isBroken ? 3 : 2,
          strokeDasharray: isBroken ? "6,6" : isWarning ? "4,4" : undefined,
          opacity: onlyProblems && !hasProblems ? 0.25 : 1,
        },
        labelStyle: {
          fontSize: 10,
          fontWeight: 600,
          fill: "var(--foreground)",
        },
        labelBgStyle: {
          fill: "var(--card)",
          fillOpacity: 0.9,
          stroke: "var(--border)",
        },
        labelBgPadding: [4, 2] as [number, number],
        labelBgBorderRadius: 4,
      };
    });
  }, [archData.edges, onlyProblems]);

  const brokenEdgesCount = useMemo(
    () => archData.edges.filter((e) => e.status === "broken").length,
    [archData.edges],
  );
  const warningEdgesCount = useMemo(
    () => archData.edges.filter((e) => e.status === "warning").length,
    [archData.edges],
  );

  // Node and Edge click handlers
  const handleNodeClick: NodeMouseHandler = useCallback(
    (_, node) => {
      const found = archData.nodes.find((n) => n.id === node.id);
      if (found) setSelectedItem({ type: "node", data: found });
    },
    [archData.nodes],
  );

  const handleEdgeClick: EdgeMouseHandler = useCallback(
    (_, edge) => {
      const found = archData.edges.find((e) => e.id === edge.id);
      if (found) setSelectedItem({ type: "edge", data: found });
    },
    [archData.edges],
  );

  const attachedIssuesForSelected = useMemo(() => {
    if (!selectedItem) return [];
    if (selectedItem.type === "node") {
      const node = selectedItem.data;
      return openIssues.filter((i) => node.issueIds.includes(i.id));
    }
    const edge = selectedItem.data;
    return openIssues.filter((i) => edge.issueIds?.includes(i.id));
  }, [selectedItem, openIssues]);

  const handleSelectIssueFromList = (issueId: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("issue", issueId);
    setSearchParams(next, { replace: true });
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-[560px] w-full rounded-xl" />
      </div>
    );
  }

  if (error) {
    return (
      <ErrorState title="Failed to load architecture graph" message={error} onRetry={loadArch} />
    );
  }

  if (archData.nodes.length === 0) {
    return (
      <EmptyState
        icon={GitFork}
        title="No architecture components found"
        description="Architecture topology has not been indexed for this codebase."
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* Header & Controls bar */}
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <GitFork className="text-primary size-5 shrink-0" />
            <h2 className="text-foreground truncate text-xl font-bold tracking-tight">
              Architecture & Interface Topology
            </h2>
          </div>
          <p className="text-muted-foreground mt-0.5 text-xs">
            Interactive multi-agent component map reflecting live cross-stack dependencies and
            contract drift.
          </p>
        </div>

        {/* Filter Switch */}
        <div className="bg-card flex shrink-0 items-center gap-2 rounded-lg border p-2 text-xs">
          <Switch id="only-problems" checked={onlyProblems} onCheckedChange={setOnlyProblems} />
          <Label htmlFor="only-problems" className="cursor-pointer text-xs select-none">
            Show only problem areas
          </Label>
        </div>
      </div>

      {/* Architecture System Summary Card */}
      <Card className="bg-card border shadow-xs">
        <CardContent className="space-y-3 p-4 sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b pb-3">
            <div className="flex items-center gap-2">
              <Layers className="text-primary size-4" />
              <h3 className="text-foreground text-sm font-semibold">
                System Topology & Boundary Summary
              </h3>
            </div>
            <div className="flex items-center gap-2">
              {brokenEdgesCount > 0 ? (
                <Badge
                  variant="outline"
                  className="border-sev-critical bg-sev-critical/12 text-sev-critical text-xs"
                >
                  <XCircle className="mr-1 size-3" /> {brokenEdgesCount} Broken Contract
                  {brokenEdgesCount > 1 ? "s" : ""}
                </Badge>
              ) : warningEdgesCount > 0 ? (
                <Badge
                  variant="outline"
                  className="border-sev-medium bg-sev-medium/12 text-sev-medium text-xs"
                >
                  <AlertTriangle className="mr-1 size-3" /> {warningEdgesCount} Schema Warning
                  {warningEdgesCount > 1 ? "s" : ""}
                </Badge>
              ) : (
                <Badge
                  variant="outline"
                  className="border-success bg-success/12 text-success text-xs"
                >
                  <CheckCircle2 className="mr-1 size-3" /> Boundaries Healthy
                </Badge>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 pt-1 md:grid-cols-3">
            {archData.nodes.map((node) => {
              const nodeIssues = openIssues.filter((i) => node.issueIds.includes(i.id));
              const critCount = nodeIssues.filter(
                (i) => i.severity === "critical" || i.severity === "high",
              ).length;
              return (
                <div key={node.id} className="bg-muted/30 space-y-1.5 rounded-lg border p-3">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-foreground font-semibold">{node.label}</span>
                    <Badge variant="secondary" className="px-1 py-0 font-mono text-[10px] uppercase">
                      {node.kind}
                    </Badge>
                  </div>
                  <p className="text-primary font-mono text-xs">{node.tech}</p>
                  <p className="text-muted-foreground line-clamp-1 text-[11px]">{node.description}</p>
                  <div className="text-muted-foreground flex items-center justify-between pt-1 text-[11px]">
                    <span>
                      {nodeIssues.length} issue{nodeIssues.length === 1 ? "" : "s"} attached
                    </span>
                    {critCount > 0 && (
                      <span className="text-sev-critical font-bold">{critCount} high-risk</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Legend */}
      <div className="bg-muted/30 text-muted-foreground flex flex-wrap items-center gap-4 rounded-lg border px-3.5 py-2 text-xs">
        <div className="text-foreground flex items-center gap-1.5 font-medium">
          <Info className="text-primary size-3.5" />
          <span>Legend:</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="bg-success size-2 rounded-full" />
          <span>Healthy Pipeline</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="bg-sev-medium size-2 rounded-full" />
          <span>Warning / Schema Drift</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="bg-sev-critical size-2 rounded-full" />
          <span>Broken Contract (Critical / High)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="border-sev-critical inline-block size-3 rounded border-2" />
          <span>Component with Vulnerabilities</span>
        </div>
      </div>

      {/* React Flow Canvas Container */}
      <div className="border-border bg-background relative h-[420px] w-full overflow-hidden rounded-xl border shadow-xs md:h-[560px]">
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={nodeTypes}
          onNodeClick={handleNodeClick}
          onEdgeClick={handleEdgeClick}
          fitView
          colorMode={themeColors.isDark ? "dark" : "light"}
          minZoom={0.3}
          maxZoom={1.5}
          preventScrolling={false}
          zoomOnScroll={false}
          panOnScroll={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background
            variant={BackgroundVariant.Dots}
            color={themeColors.border}
            gap={16}
            size={1.5}
          />
          <Controls className="!bg-card !border-border !fill-foreground" />
          <MiniMap
            className="!bg-background !border-border hidden rounded-lg sm:block"
            nodeColor={() => themeColors.primary}
            maskColor={themeColors.isDark ? "rgba(23, 10, 20, 0.75)" : "rgba(255, 243, 230, 0.75)"}
          />
        </ReactFlow>

        {/* Side Panel Overlay / Drawer */}
        <ArchSidePanel
          selectedItem={selectedItem}
          attachedIssues={attachedIssuesForSelected}
          onClose={() => setSelectedItem(null)}
        />
      </div>

      {/* Accessible List View Fallback */}
      <ArchListView
        nodes={archData.nodes}
        edges={archData.edges}
        issues={issues}
        onSelectIssue={handleSelectIssueFromList}
      />
    </div>
  );
}
