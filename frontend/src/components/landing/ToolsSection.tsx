import { landingContent } from "@/content/landing";
import { Bot } from "lucide-react";

export function ToolsSection() {
  const { supportedTools } = landingContent;

  return (
    <section className="bg-background border-t py-14">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col items-center justify-center gap-6 text-center">
          <div className="text-muted-foreground flex items-center gap-2 text-xs font-semibold tracking-wider uppercase">
            <Bot className="text-primary size-4" />
            <span>Works with your AI tools</span>
          </div>

          {/* Text-only chips */}
          <div className="flex flex-wrap items-center justify-center gap-3">
            {supportedTools.map((tool) => (
              <span
                key={tool}
                className="bg-muted/50 text-foreground hover:border-primary/50 hover:bg-muted rounded-full border px-4 py-1.5 text-sm font-medium transition-all duration-200"
              >
                {tool}
              </span>
            ))}
          </div>

          <p className="text-muted-foreground text-xs">
            No proprietary CLI required. Point MergeX AI to standard git repositories or project
            directories.
          </p>
        </div>
      </div>
    </section>
  );
}
