import React from "react";
import { renderInline } from "./markdown-inline";

interface MarkdownProps {
  content: string;
  className?: string;
}

/**
 * Micro markdown renderer that parses headings, bold text, inline code,
 * ordered & unordered lists, and tables without dangerouslySetInnerHTML.
 */
export function MicroMarkdown({ content, className }: MarkdownProps) {
  const lines = content.split("\n");
  const elements: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const rawLine = lines[i];
    if (rawLine === undefined) break;
    const line = rawLine.trim();

    // 1. Blank line
    if (!line) {
      i++;
      continue;
    }

    // 2. Headings (#, ##, ###, ####)
    if (line.startsWith("#### ")) {
      elements.push(
        <h5 key={i} className="text-foreground mt-4 mb-2 text-xs font-bold tracking-wide uppercase">
          {renderInline(line.replace("#### ", ""))}
        </h5>,
      );
      i++;
      continue;
    }
    if (line.startsWith("### ")) {
      elements.push(
        <h4 key={i} className="text-foreground mt-6 mb-2 text-sm font-bold tracking-tight">
          {renderInline(line.replace("### ", ""))}
        </h4>,
      );
      i++;
      continue;
    }
    if (line.startsWith("## ")) {
      elements.push(
        <h3 key={i} className="text-foreground mt-7 mb-3 border-b pb-1 text-base font-bold">
          {renderInline(line.replace("## ", ""))}
        </h3>,
      );
      i++;
      continue;
    }
    if (line.startsWith("# ")) {
      elements.push(
        <h2 key={i} className="text-foreground mt-8 mb-4 text-xl font-extrabold">
          {renderInline(line.replace("# ", ""))}
        </h2>,
      );
      i++;
      continue;
    }

    // 3. Markdown Table (starts with |)
    if (line.startsWith("|")) {
      const tableLines: string[] = [];
      while (i < lines.length && (lines[i] ?? "").trim().startsWith("|")) {
        const tableLine = (lines[i] ?? "").trim();
        tableLines.push(tableLine);
        i++;
      }

      if (tableLines.length >= 2) {
        const headerRow = tableLines[0] ?? "";
        // Extract headers
        const headers = headerRow
          .split("|")
          .map((c) => c.trim())
          .filter((_, idx, arr) => idx > 0 && idx < arr.length - 1);

        // Body rows (skip line 1 which is separator |---|---|)
        const bodyRows = tableLines.slice(2).map((r) =>
          r
            .split("|")
            .map((c) => c.trim())
            .filter((_, idx, arr) => idx > 0 && idx < arr.length - 1),
        );

        elements.push(
          <div key={`table-${i}`} className="bg-card my-4 overflow-x-auto rounded-lg border">
            <table className="w-full border-collapse text-left text-xs">
              <thead className="bg-muted/60 border-b">
                <tr>
                  {headers.map((h, hIdx) => (
                    <th key={hIdx} className="text-foreground p-2.5 font-semibold">
                      {renderInline(h)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-border/60 divide-y">
                {bodyRows.map((row, rIdx) => (
                  <tr key={rIdx} className="hover:bg-muted/30 transition-colors">
                    {row.map((cell, cIdx) => (
                      <td key={cIdx} className="text-muted-foreground p-2.5 align-top">
                        {renderInline(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>,
        );
      }
      continue;
    }

    // 4. Unordered List (- or *)
    if (line.startsWith("- ") || line.startsWith("* ")) {
      const listItems: string[] = [];
      while (
        i < lines.length &&
        ((lines[i] ?? "").trim().startsWith("- ") || (lines[i] ?? "").trim().startsWith("* "))
      ) {
        listItems.push((lines[i] ?? "").trim().replace(/^[-*]\s+/, ""));
        i++;
      }
      elements.push(
        <ul key={`ul-${i}`} className="text-muted-foreground my-2 ml-5 list-disc space-y-1 text-xs">
          {listItems.map((item, idx) => (
            <li key={idx} className="leading-relaxed">
              {renderInline(item)}
            </li>
          ))}
        </ul>,
      );
      continue;
    }

    // 5. Ordered List (1. , 2. )
    if (/^\d+\.\s/.test(line)) {
      const listItems: string[] = [];
      while (i < lines.length && /^\d+\.\s/.test((lines[i] ?? "").trim())) {
        listItems.push((lines[i] ?? "").trim().replace(/^\d+\.\s+/, ""));
        i++;
      }
      elements.push(
        <ol
          key={`ol-${i}`}
          className="text-muted-foreground my-2 ml-5 list-decimal space-y-1 text-xs"
        >
          {listItems.map((item, idx) => (
            <li key={idx} className="leading-relaxed">
              {renderInline(item)}
            </li>
          ))}
        </ol>,
      );
      continue;
    }

    // 6. Standard Paragraph
    elements.push(
      <p key={i} className="text-muted-foreground my-2 text-xs leading-relaxed">
        {renderInline(line)}
      </p>,
    );
    i++;
  }

  return <div className={className}>{elements}</div>;
}
