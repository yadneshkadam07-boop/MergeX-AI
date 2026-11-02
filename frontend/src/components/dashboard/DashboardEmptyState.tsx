import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { FolderGit2, SearchX, PlusCircle } from "lucide-react";
import { EmptyState } from "@/components/shared/EmptyState";

interface DashboardEmptyStateProps {
  isFiltered?: boolean;
  onClearFilters?: () => void;
}

export function DashboardEmptyState({
  isFiltered = false,
  onClearFilters,
}: DashboardEmptyStateProps) {
  if (isFiltered) {
    return (
      <EmptyState
        icon={SearchX}
        title="No matching projects found"
        description="Try refining your search keyword or changing the status filter to see other repositories."
        action={
          onClearFilters ? (
            <Button variant="outline" size="sm" onClick={onClearFilters} className="text-xs">
              Clear all filters
            </Button>
          ) : undefined
        }
      />
    );
  }

  return (
    <EmptyState
      icon={FolderGit2}
      title="No projects analyzed yet"
      description="Connect a GitHub repository to evaluate integration health, detect schema drift, and verify deployment readiness."
      action={
        <Button asChild size="default" className="gap-2 text-xs font-semibold">
          <Link to="/analyze">
            <PlusCircle className="size-4" />
            <span>Start first analysis</span>
          </Link>
        </Button>
      }
    />
  );
}
