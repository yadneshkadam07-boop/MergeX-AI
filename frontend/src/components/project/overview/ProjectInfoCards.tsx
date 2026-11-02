import type { ScanMeta } from "@/types/project";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatRelativeTime } from "@/lib/utils";
import {
  Clock,
  Cpu,
  FileCode2,
  GitBranch,
  GitCommit,
  Layers,
  ShieldCheck,
  Timer,
} from "lucide-react";

interface ProjectInfoCardsProps {
  stack: string[];
  scanMeta: ScanMeta;
  lastScannedAt: string;
}

export function ProjectInfoCards({ stack, scanMeta, lastScannedAt }: ProjectInfoCardsProps) {
  return (
    <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
      {/* Detected Stack Card */}
      <Card interactive className="bg-card border shadow-xs">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <Layers className="text-primary size-4" />
            <CardTitle className="text-sm font-semibold">Detected Stack & Architecture</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground text-xs leading-relaxed">
            Identified by autonomous AST scanners analyzing package descriptors, imports, and
            container configurations.
          </p>
          <div className="flex flex-wrap gap-2">
            {stack.map((item) => (
              <Badge
                key={item}
                variant="secondary"
                className="bg-muted/80 text-foreground px-2.5 py-1 text-xs font-medium"
              >
                {item}
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Scan Details Card */}
      <Card interactive className="bg-card border shadow-xs">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="text-primary size-4" />
            <CardTitle className="text-sm font-semibold">Diagnostic Run Metadata</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="text-muted-foreground flex items-center gap-2">
              <GitBranch className="text-foreground size-3.5 shrink-0" />
              <span>Branch:</span>
              <span className="text-foreground truncate font-mono font-bold">
                {scanMeta.branch}
              </span>
            </div>

            <div className="text-muted-foreground flex items-center gap-2">
              <GitCommit className="text-foreground size-3.5 shrink-0" />
              <span>Commit:</span>
              <span className="text-foreground font-mono font-bold">{scanMeta.commitSha}</span>
            </div>

            <div className="text-muted-foreground flex items-center gap-2">
              <FileCode2 className="text-foreground size-3.5 shrink-0" />
              <span>Files:</span>
              <span className="text-foreground font-mono font-bold">
                {scanMeta.filesScanned} files
              </span>
            </div>

            <div className="text-muted-foreground flex items-center gap-2">
              <Cpu className="text-foreground size-3.5 shrink-0" />
              <span>Agents:</span>
              <span className="text-foreground font-mono font-bold">
                {scanMeta.agentsRun} agents
              </span>
            </div>

            <div className="text-muted-foreground flex items-center gap-2">
              <Timer className="text-foreground size-3.5 shrink-0" />
              <span>Duration:</span>
              <span className="text-foreground font-mono font-bold">
                {scanMeta.durationSeconds}s
              </span>
            </div>

            <div className="text-muted-foreground flex items-center gap-2">
              <Clock className="text-foreground size-3.5 shrink-0" />
              <span>Scanned:</span>
              <span className="text-foreground truncate font-medium">
                {formatRelativeTime(lastScannedAt)}
              </span>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
