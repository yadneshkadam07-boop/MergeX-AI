import type { Project } from "@/types/project";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Link } from "react-router-dom";
import {
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  Package,
  KeyRound,
  GitCompare,
  Rocket,
  ArrowRight,
  Sparkles,
} from "lucide-react";

interface ProjectSummaryCardProps {
  project: Project;
}

export function ProjectSummaryCard({ project }: ProjectSummaryCardProps) {
  const { healthScore, severityCounts, issueCounts, stack, scanMeta } = project;
  const isCritical = severityCounts.critical > 0;
  const isHigh = severityCounts.high > 0;
  const isMedium = severityCounts.medium > 0;

  // Derive health verdict
  const verdict = isCritical
    ? {
        label: healthScore === 0 ? "Critical Risk · Score Floored (0/100)" : "Critical Risk Detected",
        color: "border-sev-critical bg-sev-critical/12 text-sev-critical",
        icon: ShieldAlert,
        summary:
          healthScore === 0
            ? `Cumulative severity deductions (${severityCounts.critical} critical findings × 15 pts = -${severityCounts.critical * 15} pts) exceed 100 points, flooring the health score at 0. Remediate these critical route contracts to recover health.`
            : "Multiple high-impact vulnerabilities require immediate resolution before production deployment.",
      }
    : isHigh
      ? {
          label: "Elevated Risk Profile",
          color: "border-sev-high bg-sev-high/12 text-sev-high",
          icon: AlertTriangle,
          summary:
            "High-severity security or integration inconsistencies detected across communication boundaries.",
        }
      : isMedium
        ? {
            label: "Moderate Maintenance Needed",
            color: "border-sev-medium bg-sev-medium/12 text-sev-medium",
            icon: AlertTriangle,
            summary:
              "System is operational but contains dependency warnings and configuration drift.",
          }
        : {
            label: "Production Ready",
            color: "border-success bg-success/12 text-success",
            icon: ShieldCheck,
            summary: "All contracts, security rules, and dependency audits passed validation.",
          };

  const VerdictIcon = verdict.icon;

  return (
    <Card className="bg-card border shadow-xs">
      <CardContent className="space-y-4 p-5 sm:p-6">
        {/* Header & Badges */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b pb-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Sparkles className="text-primary size-4" />
              <h3 className="text-foreground text-base font-bold tracking-tight">
                Executive Synthesis & Architecture Diagnostic
              </h3>
            </div>
            <p className="text-muted-foreground text-xs">
              Automated multi-layer analysis of {scanMeta.filesScanned} files across interface contracts, security, and dependencies.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className={`px-2.5 py-1 text-xs font-semibold ${verdict.color}`}>
              <VerdictIcon className="mr-1.5 size-3.5" />
              {verdict.label}
            </Badge>
          </div>
        </div>

        {/* Detected Technology Blueprint */}
        {stack.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-muted-foreground font-medium mr-1">Detected Blueprint:</span>
            {stack.map((item) => (
              <Badge key={item} variant="secondary" className="font-mono text-[11px] px-2 py-0.5">
                {item}
              </Badge>
            ))}
          </div>
        )}

        {/* Narrative & Key Risk Vectors */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
          {/* Supply Chain */}
          <div className="bg-muted/30 border rounded-lg p-3 space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                <Package className="size-3.5 text-primary" />
                <span>Supply Chain & Dependencies</span>
              </div>
              <Badge variant="outline" className="text-[10px] font-mono">
                {issueCounts.dependencies} {issueCounts.dependencies === 1 ? "finding" : "findings"}
              </Badge>
            </div>
            <p className="text-muted-foreground text-xs leading-relaxed">
              {issueCounts.dependencies > 0
                ? "Outdated or vulnerable third-party packages identified. Ensure package-lock.json integrity and update high-risk semver pins."
                : "All third-party package manifests match approved lockfile versions and pass known CVE vulnerability databases."}
            </p>
          </div>

          {/* Security */}
          <div className="bg-muted/30 border rounded-lg p-3 space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                <KeyRound className="size-3.5 text-primary" />
                <span>Security & Secrets Audit</span>
              </div>
              <Badge variant="outline" className="text-[10px] font-mono">
                {issueCounts.security} {issueCounts.security === 1 ? "finding" : "findings"}
              </Badge>
            </div>
            <p className="text-muted-foreground text-xs leading-relaxed">
              {issueCounts.security > 0
                ? "Potential secrets, overly permissive CORS policies, or unauthenticated route endpoints detected in codebase."
                : "No exposed secrets, credential leaks, or open authorization pathways detected in checked source files."}
            </p>
          </div>

          {/* Interface Contracts */}
          <div className="bg-muted/30 border rounded-lg p-3 space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                <GitCompare className="size-3.5 text-primary" />
                <span>Cross-Layer Interface Contracts</span>
              </div>
              <Badge variant="outline" className="text-[10px] font-mono">
                {issueCounts.integration} {issueCounts.integration === 1 ? "finding" : "findings"}
              </Badge>
            </div>
            <p className="text-muted-foreground text-xs leading-relaxed">
              {issueCounts.integration > 0
                ? "Schema mismatch or route discrepancy between frontend client calls and backend API controllers."
                : "Client API requests conform to backend routing signatures and database model constraints."}
            </p>
          </div>

          {/* Deployment Readiness */}
          <div className="bg-muted/30 border rounded-lg p-3 space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                <Rocket className="size-3.5 text-primary" />
                <span>Deployment & Build Readiness</span>
              </div>
              <Badge variant="outline" className="text-[10px] font-mono">
                {issueCounts.deployment} {issueCounts.deployment === 1 ? "finding" : "findings"}
              </Badge>
            </div>
            <p className="text-muted-foreground text-xs leading-relaxed">
              {issueCounts.deployment > 0
                ? "Build configuration warnings or missing container environment specifications."
                : "Docker and production environment parameters are present and properly configured."}
            </p>
          </div>
        </div>

        {/* Remediation Action Callout */}
        <div className="bg-primary/5 border border-primary/20 rounded-lg p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
          <div className="space-y-0.5">
            <span className="font-semibold text-foreground">Recommended Next Action:</span>
            <p className="text-muted-foreground">
              {healthScore === 0
                ? `Prioritize remediating the ${severityCounts.critical} critical findings using consolidated batch PR or instant git patches to lift your score above 0.`
                : isCritical
                  ? `Prioritize remediating the ${severityCounts.critical} critical findings using consolidated batch PR or instant git patches.`
                  : healthScore < 80
                    ? "Review cross-layer interface contracts and upgrade flagged dependencies to restore full health."
                    : "Codebase is in solid health. Keep dependencies up-to-date and maintain regular CI scan checks."}
            </p>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <Button asChild size="sm" variant="default" className="text-xs h-8">
              <Link to={`/project/${project.id}/architecture`}>
                <span>View Architecture</span>
                <ArrowRight className="ml-1 size-3.5" />
              </Link>
            </Button>
            <Button asChild size="sm" variant="outline" className="text-xs h-8">
              <Link to={`/project/${project.id}/docs`}>
                <span>View Full Report</span>
              </Link>
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
