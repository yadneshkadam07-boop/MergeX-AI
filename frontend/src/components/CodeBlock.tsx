import { Check, Copy } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface CopyButtonProps {
  value: string;
  label?: string;
  className?: string;
}

/** Copy to clipboard, with the confirmation that makes it feel reliable. */
export function CopyButton({ value, label = "Copy", className }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1_600);
    return () => clearTimeout(timer);
  }, [copied]);

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      // Clipboard access can be denied (insecure origin, permissions).
      // Selecting the text by hand still works, so this stays silent.
    }
  }, [value]);

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={() => void copy()}
      className={cn("h-7 gap-1.5 px-2 text-xs", className)}
      aria-label={copied ? "Copied" : label}
    >
      {copied ? (
        <Check className="size-3.5" aria-hidden />
      ) : (
        <Copy className="size-3.5" aria-hidden />
      )}
      {copied ? "Copied" : label}
    </Button>
  );
}

interface CodeBlockProps {
  code: string;
  /** 1-based line number within the file that `code` starts at. */
  startLine?: number | null;
  /** 1-based range to highlight, inclusive. */
  highlight?: { start: number; end: number } | null;
  title?: string | undefined;
  /** Rendered in the corner. Pass `false` for a snippet nobody would copy. */
  copyable?: boolean;
  tone?: "neutral" | "removed" | "added";
  className?: string;
}

const TONE_STYLES: Record<NonNullable<CodeBlockProps["tone"]>, string> = {
  neutral: "border-border bg-muted/40",
  removed: "border-severity-critical/25 bg-severity-critical/8",
  added: "border-severity-ok/25 bg-severity-ok/8",
};

/**
 * A code snippet with optional line numbers and a highlighted range.
 *
 * Evidence is the thing that makes a finding checkable, so the highlighted
 * line is the point of the component: a user should be able to see the
 * offending line without counting rows.
 */
export function CodeBlock({
  code,
  startLine = null,
  highlight = null,
  title,
  copyable = true,
  tone = "neutral",
  className,
}: CodeBlockProps) {
  const lines = code.replace(/\n$/, "").split("\n");

  return (
    <figure className={cn("overflow-hidden rounded-lg border", TONE_STYLES[tone], className)}>
      {title || copyable ? (
        <figcaption className="border-border/60 flex items-center justify-between gap-2 border-b px-3 py-1.5">
          <span className="text-muted-foreground truncate font-mono text-xs">{title}</span>
          {copyable ? <CopyButton value={code} /> : null}
        </figcaption>
      ) : null}

      <pre className="overflow-x-auto p-3 text-xs leading-relaxed">
        <code className="font-mono">
          {lines.map((line, index) => {
            const lineNumber = startLine !== null ? startLine + index : null;
            const isHighlighted =
              highlight !== null &&
              lineNumber !== null &&
              lineNumber >= highlight.start &&
              lineNumber <= highlight.end;

            return (
              <span
                key={index}
                data-highlighted={isHighlighted || undefined}
                className={cn(
                  "grid grid-cols-[auto_1fr] gap-3 px-1",
                  isHighlighted &&
                    "bg-severity-high/15 border-severity-high -mx-1 border-l-2 px-1 pl-[2px]",
                )}
              >
                {lineNumber !== null ? (
                  <span className="text-muted-foreground/70 w-10 text-right tabular-nums select-none">
                    {lineNumber}
                  </span>
                ) : (
                  <span className="w-0" />
                )}
                <span className="whitespace-pre">{line || " "}</span>
              </span>
            );
          })}
        </code>
      </pre>
    </figure>
  );
}
