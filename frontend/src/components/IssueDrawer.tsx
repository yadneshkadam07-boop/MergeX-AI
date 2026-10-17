import { ArrowRight, FileCode2, Sparkles, Wrench } from "lucide-react";

import type { ReportIssue } from "@/api/analyses";
import { CodeBlock, CopyButton } from "@/components/CodeBlock";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { CATEGORY_LABELS, SEVERITY_STYLES } from "@/lib/severity";
import { cn } from "@/lib/utils";

interface IssueDrawerProps {
  issue: ReportIssue | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Where the explanation came from. Users deserve to know. */
function SourceBadge({ source }: { source: string | null }) {
  if (source === "gemini") {
    return (
      <Badge variant="outline" className="gap-1 border-sky-500/30 bg-sky-500/10 text-sky-500">
        <Sparkles className="size-3" aria-hidden />
        AI explanation
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="gap-1">
      <Wrench className="size-3" aria-hidden />
      Rule template
    </Badge>
  );
}

function Field({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div className="space-y-1">
      <p className="text-muted-foreground text-xs tracking-wide uppercase">{label}</p>
      <p className="font-mono text-sm break-words">{value}</p>
    </div>
  );
}

/**
 * Everything known about one finding.
 *
 * The order is deliberate: what is wrong, the evidence that proves it, why
 * it matters, then the edit to make. A user should be able to verify the
 * finding before reading an explanation of it — the explanation is the part
 * a model may have written.
 */
export function IssueDrawer({ issue, open, onOpenChange }: IssueDrawerProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full gap-0 overflow-y-auto sm:max-w-xl"
        aria-describedby={undefined}
      >
        {issue ? (
          <>
            <SheetHeader className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge
                  variant="outline"
                  className={cn("font-medium", SEVERITY_STYLES[issue.severity].badge)}
                >
                  {SEVERITY_STYLES[issue.severity].label}
                </Badge>
                <Badge variant="secondary">{CATEGORY_LABELS[issue.category]}</Badge>
                <Badge variant="outline" className="font-mono text-xs">
                  {issue.rule_id}
                </Badge>
                <span className="text-muted-foreground text-xs">
                  confidence {Math.round(issue.confidence * 100)}%
                </span>
              </div>

              <SheetTitle className="text-xl leading-snug">{issue.title}</SheetTitle>
              <SheetDescription className="text-sm">{issue.description}</SheetDescription>

              {issue.file_path ? (
                <p className="text-muted-foreground flex items-center gap-1.5 font-mono text-xs">
                  <FileCode2 className="size-3.5 shrink-0" aria-hidden />
                  <span className="break-all">
                    {issue.file_path}
                    {issue.line_start !== null ? `:${issue.line_start}` : ""}
                    {issue.line_end !== null && issue.line_end !== issue.line_start
                      ? `-${issue.line_end}`
                      : ""}
                  </span>
                </p>
              ) : null}
            </SheetHeader>

            <div className="space-y-6 px-4 pb-8">
              {issue.evidence ? (
                <section className="space-y-2">
                  <h3 className="text-sm font-medium">Evidence</h3>
                  <CodeBlock
                    code={issue.evidence}
                    startLine={issue.line_start}
                    highlight={
                      issue.line_start !== null
                        ? { start: issue.line_start, end: issue.line_end ?? issue.line_start }
                        : null
                    }
                    title={issue.file_path ?? undefined}
                  />
                  <p className="text-muted-foreground text-xs">
                    Credentials in evidence are masked before they are stored.
                  </p>
                </section>
              ) : null}

              {issue.expected || issue.actual ? (
                <section className="grid gap-4 sm:grid-cols-2">
                  <Field label="Expected" value={issue.expected} />
                  <Field label="Actual" value={issue.actual} />
                </section>
              ) : null}

              {issue.explanation ? (
                <>
                  <Separator />
                  <section className="space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="text-sm font-medium">Why this matters</h3>
                      <SourceBadge source={issue.explanation_source} />
                    </div>
                    <p className="text-muted-foreground text-sm leading-relaxed">
                      {issue.explanation}
                    </p>
                  </section>
                </>
              ) : null}

              {issue.suggested_fix ? (
                <section className="space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-sm font-medium">Suggested fix</h3>
                    <CopyButton value={issue.suggested_fix} label="Copy fix" />
                  </div>
                  <p className="text-sm leading-relaxed">{issue.suggested_fix}</p>

                  {issue.fix_before || issue.fix_after ? (
                    <div className="space-y-2">
                      {issue.fix_before ? (
                        <CodeBlock
                          code={issue.fix_before}
                          title="before"
                          tone="removed"
                          copyable={false}
                        />
                      ) : null}
                      {issue.fix_after ? (
                        <>
                          <ArrowRight
                            className="text-muted-foreground mx-auto size-4 rotate-90"
                            aria-hidden
                          />
                          <CodeBlock code={issue.fix_after} title="after" tone="added" />
                        </>
                      ) : null}
                    </div>
                  ) : null}
                </section>
              ) : null}

              <p className="text-muted-foreground border-t pt-4 text-xs">
                Found by deterministic analysis ({issue.rule_id}).{" "}
                {issue.explanation_source === "gemini"
                  ? "The explanation and fix above were written by Gemini; the finding itself was not."
                  : "The explanation and fix above come from this rule's built-in template."}
              </p>
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
