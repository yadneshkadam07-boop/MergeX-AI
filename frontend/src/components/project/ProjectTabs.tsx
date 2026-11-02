import { useRef, useEffect } from "react";
import { NavLink, useParams } from "react-router-dom";
import type { IssueCounts } from "@/types/project";
import { cn } from "@/lib/utils";
import {
  FileText,
  GitFork,
  LayoutDashboard,
  Package,
  Rocket,
  ShieldCheck,
  Zap,
} from "lucide-react";

interface ProjectTabsProps {
  issueCounts: IssueCounts;
}

interface TabConfig {
  name: string;
  to: string;
  icon: typeof LayoutDashboard;
  countKey?: keyof IssueCounts;
  end?: boolean;
}

const TABS: TabConfig[] = [
  {
    name: "Overview",
    to: "",
    icon: LayoutDashboard,
    end: true,
  },
  {
    name: "Integration",
    to: "integration",
    icon: Zap,
    countKey: "integration",
  },
  {
    name: "Security",
    to: "security",
    icon: ShieldCheck,
    countKey: "security",
  },
  {
    name: "Dependencies",
    to: "dependencies",
    icon: Package,
    countKey: "dependencies",
  },
  {
    name: "Deploy check",
    to: "deploy",
    icon: Rocket,
    countKey: "deployment",
  },
  {
    name: "Architecture",
    to: "architecture",
    icon: GitFork,
  },
  {
    name: "Docs",
    to: "docs",
    icon: FileText,
  },
];

export function ProjectTabs({ issueCounts }: ProjectTabsProps) {
  const { id } = useParams<{ id: string }>();
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll active tab into view horizontally on mobile
  useEffect(() => {
    if (containerRef.current) {
      const activeEl = containerRef.current.querySelector<HTMLElement>("[aria-current='page']");
      if (activeEl) {
        activeEl.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
      }
    }
  });

  return (
    <div className="bg-background/95 sticky top-16 z-20 -mx-4 border-b px-4 backdrop-blur-md sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
      <div
        ref={containerRef}
        className="no-scrollbar flex items-center gap-1.5 overflow-x-auto scroll-smooth py-2"
        role="tablist"
      >
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const targetUrl = tab.to ? `/project/${id}/${tab.to}` : `/project/${id}`;
          const issueCount = tab.countKey ? issueCounts[tab.countKey] : undefined;

          const navLinkProps = tab.end ? { end: true } : {};

          return (
            <NavLink
              key={tab.name}
              to={targetUrl}
              {...navLinkProps}
              className={({ isActive }) =>
                cn(
                  "focus-visible:ring-ring flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium whitespace-nowrap transition-colors select-none focus:outline-hidden focus-visible:ring-2",
                  isActive
                    ? "bg-primary text-primary-foreground font-semibold shadow-xs"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <Icon
                    className={cn(
                      "size-4 shrink-0",
                      isActive ? "text-primary-foreground" : "text-muted-foreground",
                    )}
                  />
                  <span>{tab.name}</span>
                  {typeof issueCount === "number" && issueCount > 0 && (
                    <span
                      className={cn(
                        "py-0.2 rounded-full px-1.5 font-mono text-[11px] font-bold",
                        isActive
                          ? "bg-primary-foreground/20 text-primary-foreground"
                          : "bg-muted-foreground/15 text-muted-foreground",
                      )}
                    >
                      {issueCount}
                    </span>
                  )}
                </>
              )}
            </NavLink>
          );
        })}
      </div>
    </div>
  );
}
