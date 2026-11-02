import React from "react";

/**
 * Parses inline bold (**text**), inline code (`code`), and links [text](url) safely into React nodes.
 */
export function renderInline(text: string): React.JSX.Element[] {
  // Regex splitting on code, bold, links
  const tokens = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g);

  return tokens
    .map((token, idx) => {
      if (!token) return null;

      // Inline code `...`
      if (token.startsWith("`") && token.endsWith("`")) {
        return (
          <code
            key={idx}
            className="bg-muted text-foreground rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold"
          >
            {token.slice(1, -1)}
          </code>
        );
      }

      // Bold **...**
      if (token.startsWith("**") && token.endsWith("**")) {
        return (
          <strong key={idx} className="text-foreground font-semibold">
            {renderInline(token.slice(2, -2))}
          </strong>
        );
      }

      // Markdown link [text](url)
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (linkMatch && linkMatch[1] && linkMatch[2]) {
        return (
          <a
            key={idx}
            href={linkMatch[2]}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline underline-offset-2 hover:opacity-80"
          >
            {linkMatch[1]}
          </a>
        );
      }

      return <span key={idx}>{token}</span>;
    })
    .filter((n): n is React.JSX.Element => n !== null);
}
