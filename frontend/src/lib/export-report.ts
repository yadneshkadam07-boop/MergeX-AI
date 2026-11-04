import { getReport } from "@/lib/api";
import { toast } from "sonner";

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
