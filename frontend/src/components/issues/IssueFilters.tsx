import { useSearchParams } from "react-router-dom";
import type { IssueSeverity } from "@/types/project";
import type { IssueStatus } from "@/types/issue";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface IssueFiltersProps {
  totalCount: number;
  filteredCount: number;
  className?: string;
}

const SEVERITIES: { value: IssueSeverity; label: string; activeClasses: string }[] = [
  {
    value: "critical",
    label: "Critical",
    activeClasses: "bg-sev-critical/15 text-sev-critical border-sev-critical font-bold",
  },
  {
    value: "high",
    label: "High",
    activeClasses: "bg-sev-high/15 text-sev-high border-sev-high font-bold",
  },
  {
    value: "medium",
    label: "Medium",
    activeClasses: "bg-sev-medium/15 text-sev-medium border-sev-medium font-bold",
  },
  {
    value: "low",
    label: "Low",
    activeClasses: "bg-sev-low/15 text-sev-low border-sev-low font-bold",
  },
];

export function IssueFilters({ totalCount, filteredCount, className }: IssueFiltersProps) {
  const [searchParams, setSearchParams] = useSearchParams();

  const searchQuery = searchParams.get("q") || "";
  const selectedSeverities = searchParams.get("severity")
    ? searchParams.get("severity")!.split(",").filter(Boolean)
    : [];
  const statusFilter = (searchParams.get("status") as IssueStatus | "all") || "open";

  const isFiltered = Boolean(
    searchQuery || selectedSeverities.length > 0 || statusFilter !== "open",
  );

  const updateParam = (key: string, val: string | null) => {
    const next = new URLSearchParams(searchParams);
    if (!val || val === "all") {
      next.delete(key);
    } else {
      next.set(key, val);
    }
    setSearchParams(next, { replace: true });
  };

  const toggleSeverity = (sev: IssueSeverity) => {
    const next = new URLSearchParams(searchParams);
    let updated: string[];
    if (selectedSeverities.includes(sev)) {
      updated = selectedSeverities.filter((s) => s !== sev);
    } else {
      updated = [...selectedSeverities, sev];
    }

    if (updated.length === 0) {
      next.delete("severity");
    } else {
      next.set("severity", updated.join(","));
    }
    setSearchParams(next, { replace: true });
  };

  const clearFilters = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("q");
    next.delete("severity");
    next.delete("status");
    setSearchParams(next, { replace: true });
  };

  return (
    <div
      className={cn(
        "bg-card/60 space-y-3.5 rounded-xl border p-4 shadow-2xs backdrop-blur-xs",
        className,
      )}
    >
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        {/* Search input */}
        <div className="relative w-full max-w-md min-w-0 flex-1">
          <Search className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <Input
            placeholder="Search by title, file, or path..."
            value={searchQuery}
            onChange={(e) => updateParam("q", e.target.value || null)}
            className="h-9 w-full pl-9 text-xs"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => updateParam("q", null)}
              className="text-muted-foreground hover:text-foreground absolute top-1/2 right-2.5 -translate-y-1/2"
              aria-label="Clear search query"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>

        {/* Status dropdown */}
        <div className="flex w-full shrink-0 items-center gap-2 sm:w-auto">
          <span className="text-muted-foreground shrink-0 text-xs font-medium">Status:</span>
          <Select
            value={statusFilter}
            onValueChange={(val) => updateParam("status", val === "open" ? null : val)}
          >
            <SelectTrigger className="min-h-9 w-full text-xs font-medium sm:w-36">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="open">Open (Default)</SelectItem>
              <SelectItem value="resolved">Resolved</SelectItem>
              <SelectItem value="ignored">Ignored</SelectItem>
              <SelectItem value="all">All Statuses</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Severity chips & Count bar */}
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3 border-t pt-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-muted-foreground mr-1 text-xs font-medium">Severity:</span>
          {SEVERITIES.map((item) => {
            const isSelected = selectedSeverities.includes(item.value);
            return (
              <button
                key={item.value}
                type="button"
                onClick={() => toggleSeverity(item.value)}
                className={cn(
                  "cursor-pointer rounded-md border px-2.5 py-1 text-xs font-semibold transition-all select-none",
                  isSelected
                    ? item.activeClasses
                    : "border-border/60 bg-muted/40 text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
                aria-pressed={isSelected}
              >
                {item.label}
              </button>
            );
          })}
        </div>

        {/* Filter result count & Reset */}
        <div className="text-muted-foreground flex min-w-0 flex-wrap items-center gap-2 text-xs sm:gap-3">
          <span className="truncate">
            Showing <strong className="text-foreground">{filteredCount}</strong> of {totalCount}{" "}
            issue{totalCount === 1 ? "" : "s"}
          </span>
          {isFiltered && (
            <Button
              variant="ghost"
              size="sm"
              onClick={clearFilters}
              className="text-primary hover:text-primary min-h-7 px-2 text-xs"
            >
              Clear filters
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
