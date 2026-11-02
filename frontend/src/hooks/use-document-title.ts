import { useEffect } from "react";

/**
 * Sets document.title dynamically, adhering to "Section | Project / Sub | MergeX AI".
 */
export function useDocumentTitle(title?: string, projectContext?: string) {
  useEffect(() => {
    const parts: string[] = [];
    if (title) parts.push(title);
    if (projectContext) parts.push(projectContext);
    parts.push("MergeX AI");

    document.title = parts.join(" | ");
  }, [title, projectContext]);
}
