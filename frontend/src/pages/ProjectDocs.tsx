import { useEffect, useState, useRef, useCallback } from "react";
import { useProject } from "@/hooks/use-project";
import type { ProjectReport } from "@/types/report";
import { getReport } from "@/lib/api";
import { MicroMarkdown } from "@/lib/markdown";
import { formatRelativeTime } from "@/lib/utils";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ButtonRow } from "@/components/ui/button-row";
import { Skeleton } from "@/components/ui/skeleton";
import { Check, Copy, Download, FileText, Printer, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

export function ProjectDocs() {
  const { project } = useProject();
  useDocumentTitle("Documentation", project.name);
  const [report, setReport] = useState<ProjectReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeSectionId, setActiveSectionId] = useState<string>("");
  const [copied, setCopied] = useState(false);

  const observerRef = useRef<IntersectionObserver | null>(null);

  const loadReportData = useCallback(() => {
    setLoading(true);
    setError(null);
    getReport(project.id)
      .then((data) => {
        setReport(data);
        if (data.sections.length > 0 && !activeSectionId) {
          const firstSection = data.sections[0];
          if (firstSection) {
            setActiveSectionId(firstSection.id);
          }
        }
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to fetch project report:", err);
        setError(err instanceof Error ? err.message : "Failed to generate project documentation.");
        setLoading(false);
      });
  }, [project.id, activeSectionId]);

  useEffect(() => {
    loadReportData();
  }, [loadReportData]);

  // Scroll spy via IntersectionObserver
  useEffect(() => {
    if (!report) return;

    observerRef.current = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setActiveSectionId(entry.target.id);
          }
        });
      },
      {
        rootMargin: "-20% 0px -60% 0px",
        threshold: 0.1,
      },
    );

    report.sections.forEach((section) => {
      const el = document.getElementById(section.id);
      if (el && observerRef.current) {
        observerRef.current.observe(el);
      }
    });

    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
      }
    };
  }, [report]);

  const scrollToSection = (sectionId: string) => {
    setActiveSectionId(sectionId);
    const el = document.getElementById(sectionId);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      el.focus({ preventScroll: true });
    }
  };

  const handleDownloadMarkdown = () => {
    if (!report) return;
    const fullMarkdown = report.sections
      .map((s) => `# ${s.title}\n\n${s.markdown}`)
      .join("\n\n---\n\n");

    const blob = new Blob([fullMarkdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${project.name}-diagnostic-report.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast.success("Markdown report downloaded");
  };

  const handleCopyMarkdown = async () => {
    if (!report) return;
    const fullMarkdown = report.sections
      .map((s) => `# ${s.title}\n\n${s.markdown}`)
      .join("\n\n---\n\n");

    await navigator.clipboard.writeText(fullMarkdown);
    setCopied(true);
    toast.success("Markdown documentation copied to clipboard");
    setTimeout(() => setCopied(false), 2000);
  };

  const handlePrintPdf = () => {
    window.print();
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
          <Skeleton className="hidden h-96 rounded-xl lg:col-span-3 lg:block" />
          <Skeleton className="h-[600px] rounded-xl lg:col-span-9" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <ErrorState title="Failed to load documentation" message={error} onRetry={loadReportData} />
    );
  }

  if (!report || report.sections.length === 0) {
    return (
      <EmptyState
        icon={FileText}
        title="No documentation generated"
        description="The automated architecture and contract report is not available for this project."
        action={
          <Button variant="outline" size="sm" onClick={loadReportData} className="gap-1.5 text-xs">
            <RefreshCw className="size-3.5" />
            <span>Regenerate Report</span>
          </Button>
        }
      />
    );
  }

  return (
    <div className="print-report-container space-y-6">
      {/* Header & Export Actions (Hidden during print) */}
      <div className="no-print flex min-w-0 flex-col gap-4 border-b pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <FileText className="text-primary size-5 shrink-0" />
            <h2 className="text-foreground truncate text-xl font-bold tracking-tight">
              Synthesized System Documentation
            </h2>
          </div>
          <p className="text-muted-foreground mt-0.5 text-xs">
            Generated {formatRelativeTime(report.generatedAt)} based on code AST and active issue
            states.
          </p>
        </div>

        {/* Action Buttons */}
        <ButtonRow align="start" className="shrink-0 sm:justify-end">
          <Button
            variant="outline"
            size="sm"
            onClick={loadReportData}
            className="gap-1.5 text-xs"
            title="Regenerate report"
          >
            <RefreshCw className="size-3.5" />
            <span className="hidden sm:inline">Regenerate</span>
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={handleCopyMarkdown}
            className="gap-1.5 text-xs"
            aria-live="polite"
          >
            {copied ? <Check className="text-success size-3.5" /> : <Copy className="size-3.5" />}
            <span>{copied ? "Copied" : "Copy Markdown"}</span>
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={handleDownloadMarkdown}
            className="gap-1.5 text-xs"
          >
            <Download className="size-3.5" />
            <span>Download .md</span>
          </Button>

          <Button size="sm" onClick={handlePrintPdf} className="gap-1.5 text-xs font-semibold">
            <Printer className="size-3.5" />
            <span>Print / PDF</span>
          </Button>
        </ButtonRow>
      </div>

      {/* Mobile Table of Contents Quick Select (Hidden during print) */}
      <div className="no-print lg:hidden">
        <label
          htmlFor="mobile-toc"
          className="text-muted-foreground mb-1.5 block text-xs font-semibold uppercase"
        >
          Jump to section
        </label>
        <select
          id="mobile-toc"
          value={activeSectionId}
          onChange={(e) => scrollToSection(e.target.value)}
          className="border-input bg-background text-foreground focus:ring-ring h-9 w-full rounded-md border px-3 py-1 text-xs focus:ring-2 focus:outline-hidden"
        >
          {report.sections.map((section) => (
            <option key={section.id} value={section.id}>
              {section.title}
            </option>
          ))}
        </select>
      </div>

      {/* 2-Column Layout */}
      <div className="grid grid-cols-1 items-start gap-8 lg:grid-cols-12">
        {/* Left Column: Sticky Table of Contents (Desktop only, hidden during print) */}
        <nav
          aria-label="Table of contents"
          className="no-print bg-card sticky top-36 hidden space-y-1 rounded-xl border p-4 shadow-2xs lg:col-span-3 lg:block"
        >
          <span className="text-muted-foreground mb-2 block border-b pb-2 text-xs font-bold tracking-wider uppercase">
            Table of Contents
          </span>
          <div className="space-y-1">
            {report.sections.map((section) => {
              const isActive = activeSectionId === section.id;
              return (
                <button
                  key={section.id}
                  type="button"
                  onClick={() => scrollToSection(section.id)}
                  className={cn(
                    "w-full cursor-pointer rounded-md px-2.5 py-1.5 text-left text-xs transition-colors",
                    isActive
                      ? "bg-primary text-primary-foreground font-semibold shadow-xs"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  {section.title}
                </button>
              );
            })}
          </div>
        </nav>

        {/* Right Column: Full Document Report */}
        <div className="space-y-8 lg:col-span-9">
          {report.sections.map((section, idx) => (
            <Card
              key={section.id}
              id={section.id}
              tabIndex={-1}
              className={cn(
                "bg-card border shadow-xs focus:outline-hidden",
                idx > 0 && "print-page-break",
              )}
            >
              <CardContent className="space-y-4 p-6">
                <div className="border-b pb-3">
                  <h3 className="text-foreground text-lg font-bold tracking-tight">
                    {section.title}
                  </h3>
                </div>
                <MicroMarkdown content={section.markdown} />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
