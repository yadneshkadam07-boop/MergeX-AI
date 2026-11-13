import { getReport } from "@/lib/api";
import { toast } from "sonner";

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function simpleMarkdownToHtml(md: string): string {
  // Convert basic markdown elements to safe HTML for print formatting
  const lines = md.split("\n");
  const htmlLines: string[] = [];
  let inCodeBlock = false;
  let codeBuffer: string[] = [];

  for (const line of lines) {
    if (line.startsWith("```")) {
      if (inCodeBlock) {
        htmlLines.push(`<pre><code>${escapeHtml(codeBuffer.join("\n"))}</code></pre>`);
        codeBuffer = [];
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeBuffer.push(line);
      continue;
    }

    if (line.startsWith("### ")) {
      htmlLines.push(`<h3>${escapeHtml(line.slice(4))}</h3>`);
    } else if (line.startsWith("## ")) {
      htmlLines.push(`<h2>${escapeHtml(line.slice(3))}</h2>`);
    } else if (line.startsWith("# ")) {
      htmlLines.push(`<h1>${escapeHtml(line.slice(2))}</h1>`);
    } else if (line.startsWith("- ") || line.startsWith("* ")) {
      htmlLines.push(`<li>${escapeHtml(line.slice(2))}</li>`);
    } else if (line.trim() === "") {
      htmlLines.push("<br/>");
    } else {
      // Basic inline backtick code and bold
      const formatted = escapeHtml(line)
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      htmlLines.push(`<p>${formatted}</p>`);
    }
  }

  if (inCodeBlock && codeBuffer.length > 0) {
    htmlLines.push(`<pre><code>${escapeHtml(codeBuffer.join("\n"))}</code></pre>`);
  }

  return htmlLines.join("\n");
}

/**
 * Downloads the full diagnostic report for a project as a formatted Markdown file.
 */
export async function exportReportMarkdown(
  projectId: string,
  projectName: string,
): Promise<boolean> {
  try {
    const report = await getReport(projectId);
    if (!report || !report.sections || report.sections.length === 0) {
      toast.error("Diagnostic report is not yet generated for this project.");
      return false;
    }

    const fullMarkdown = report.sections
      .map((s) => `# ${s.title}\n\n${s.markdown}`)
      .join("\n\n---\n\n");

    const blob = new Blob([fullMarkdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const sanitizedName = projectName.toLowerCase().replace(/[^a-z0-9_-]/g, "-");
    a.download = `${sanitizedName}-diagnostic-report.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    toast.success("Diagnostic report downloaded successfully!");
    return true;
  } catch (err) {
    console.error("Failed to export report:", err);
    toast.error("Failed to export report. Please try again.");
    return false;
  }
}

/**
 * Opens a print-formatted executive view of the diagnostic report for PDF generation.
 */
export async function exportReportPdf(projectId: string, projectName: string): Promise<boolean> {
  try {
    const report = await getReport(projectId);
    if (!report || !report.sections || report.sections.length === 0) {
      toast.error("Diagnostic report is not yet generated for this project.");
      return false;
    }

    const printWindow = window.open("", "_blank");
    if (!printWindow) {
      toast.error("Popup blocked. Please allow popups to print or save PDF.");
      return false;
    }

    const sectionsHtml = report.sections
      .map(
        (s) => `
        <section class="report-section">
          <h2>${escapeHtml(s.title)}</h2>
          <div class="content">${simpleMarkdownToHtml(s.markdown)}</div>
        </section>
      `,
      )
      .join("<hr class='divider' />");

    printWindow.document.write(`
      <!DOCTYPE html>
      <html>
        <head>
          <meta charset="utf-8" />
          <title>${escapeHtml(projectName)} — MergeX AI Audit Report</title>
          <style>
            @page { margin: 18mm; size: A4; }
            body {
              font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
              color: #0f172a;
              line-height: 1.6;
              padding: 24px;
              max-width: 900px;
              margin: 0 auto;
            }
            .header {
              border-bottom: 2px solid #e2e8f0;
              padding-bottom: 16px;
              margin-bottom: 24px;
              display: flex;
              justify-content: space-between;
              align-items: flex-start;
            }
            .logo { font-size: 22px; font-weight: 800; color: #4f46e5; letter-spacing: -0.5px; }
            .meta { font-size: 13px; color: #64748b; text-align: right; }
            h1 { font-size: 24px; font-weight: 700; margin: 4px 0 2px 0; }
            h2 { font-size: 18px; font-weight: 600; color: #1e293b; margin: 20px 0 10px 0; }
            h3 { font-size: 15px; font-weight: 600; color: #334155; margin: 14px 0 6px 0; }
            p { margin: 6px 0; font-size: 14px; }
            ul, ol { padding-left: 20px; margin: 6px 0; font-size: 14px; }
            li { margin: 3px 0; }
            code { background: #f1f5f9; padding: 2px 5px; border-radius: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
            pre { background: #0f172a; color: #f8fafc; padding: 12px; border-radius: 6px; overflow-x: auto; }
            pre code { background: none; color: inherit; padding: 0; }
            .divider { border: 0; border-top: 1px dashed #cbd5e1; margin: 24px 0; }
            .footer { margin-top: 40px; font-size: 11px; color: #94a3b8; text-align: center; border-top: 1px solid #e2e8f0; padding-top: 12px; }
            .print-btn-bar {
              margin-bottom: 20px;
              padding: 12px;
              background: #eef2ff;
              border: 1px solid #c7d2fe;
              border-radius: 8px;
              display: flex;
              justify-content: space-between;
              align-items: center;
            }
            .print-btn {
              background: #4f46e5;
              color: white;
              border: none;
              padding: 8px 16px;
              border-radius: 6px;
              font-weight: 600;
              cursor: pointer;
              font-size: 13px;
            }
            @media print {
              .no-print { display: none !important; }
              body { padding: 0; }
            }
          </style>
        </head>
        <body>
          <div class="no-print print-btn-bar">
            <span style="font-size: 13px; color: #3730a3; font-weight: 500;">
              Executive Report Preview ready. Click the button to print or save as PDF.
            </span>
            <button class="print-btn" onclick="window.print()">Print / Save PDF</button>
          </div>
          <div class="header">
            <div>
              <div class="logo">MergeX AI</div>
              <h1>Executive Audit & Health Report</h1>
              <div style="font-size: 14px; font-weight: 600; color: #334155;">Project: ${escapeHtml(projectName)}</div>
            </div>
            <div class="meta">
              <div><strong>Generated:</strong> ${new Date().toLocaleDateString(undefined, { dateStyle: "medium" })}</div>
              <div>Deterministic Multi-Layer Verification</div>
            </div>
          </div>
          ${sectionsHtml}
          <div class="footer">
            Generated by MergeX AI · Multi-Layer Software Integrity & Security Auditor
          </div>
          <script>
            setTimeout(() => { window.print(); }, 400);
          </script>
        </body>
      </html>
    `);
    printWindow.document.close();
    toast.success("Executive PDF preview opened!");
    return true;
  } catch (err) {
    console.error("Failed to export PDF:", err);
    toast.error("Failed to generate PDF. Please try again.");
    return false;
  }
}
