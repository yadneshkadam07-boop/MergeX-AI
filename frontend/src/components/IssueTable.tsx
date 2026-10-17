import { Search, X } from "lucide-react";
import { useMemo, useState } from "react";

import {
  CATEGORIES,
  SEVERITIES,
  type Category,
  type ReportIssue,
  type Severity,
} from "@/api/analyses";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ALL, filterIssues } from "@/lib/issues";
import { CATEGORY_LABELS, SEVERITY_STYLES } from "@/lib/severity";
import { cn } from "@/lib/utils";

interface IssueTableProps {
  issues: ReportIssue[];
  onSelect: (issue: ReportIssue) => void;
  selectedId?: string | undefined;
}

export function IssueTable({ issues, onSelect, selectedId }: IssueTableProps) {
  const [severity, setSeverity] = useState<Severity | typeof ALL>(ALL);
  const [category, setCategory] = useState<Category | typeof ALL>(ALL);
  const [query, setQuery] = useState("");

  const filtered = useMemo(
    () => filterIssues(issues, { severity, category, query }),
    [issues, severity, category, query],
  );

  const hasFilters = severity !== ALL || category !== ALL || query.trim() !== "";
  const clear = () => {
    setSeverity(ALL);
    setCategory(ALL);
    setQuery("");
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search
            className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
            aria-hidden
          />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search title, rule ID or file…"
            aria-label="Search issues"
            className="pl-9"
          />
        </div>

        <Select
          value={severity}
          onValueChange={(value) => setSeverity(value as Severity | typeof ALL)}
        >
          <SelectTrigger className="sm:w-44" aria-label="Filter by severity">
            <SelectValue placeholder="Severity" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All severities</SelectItem>
            {SEVERITIES.map((value) => (
              <SelectItem key={value} value={value}>
                {SEVERITY_STYLES[value].label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={category}
          onValueChange={(value) => setCategory(value as Category | typeof ALL)}
        >
          <SelectTrigger className="sm:w-48" aria-label="Filter by category">
            <SelectValue placeholder="Category" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All categories</SelectItem>
            {CATEGORIES.map((value) => (
              <SelectItem key={value} value={value}>
                {CATEGORY_LABELS[value]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {hasFilters ? (
          <Button variant="ghost" size="sm" onClick={clear}>
            <X className="size-4" aria-hidden />
            Clear
          </Button>
        ) : null}
      </div>

      <p className="text-muted-foreground text-sm" role="status">
        {filtered.length === issues.length
          ? `${issues.length} issue${issues.length === 1 ? "" : "s"}`
          : `${filtered.length} of ${issues.length} issues`}
      </p>

      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-28">Severity</TableHead>
              <TableHead>Issue</TableHead>
              <TableHead className="hidden w-40 md:table-cell">Category</TableHead>
              <TableHead className="hidden w-64 lg:table-cell">Location</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="text-muted-foreground py-10 text-center">
                  No issues match these filters.
                </TableCell>
              </TableRow>
            ) : (
              filtered.map((issue) => (
                <TableRow
                  key={issue.id}
                  onClick={() => onSelect(issue)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect(issue);
                    }
                  }}
                  // Focusable and operable, but still a row: giving a <tr>
                  // role="button" would strip the table semantics a screen
                  // reader needs to announce the columns.
                  tabIndex={0}
                  aria-label={`${SEVERITY_STYLES[issue.severity].label}: ${issue.title}`}
                  className={cn("cursor-pointer", selectedId === issue.id && "bg-accent/60")}
                >
                  <TableCell>
                    <Badge
                      variant="outline"
                      className={cn("font-medium", SEVERITY_STYLES[issue.severity].badge)}
                    >
                      {SEVERITY_STYLES[issue.severity].label}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <span className="font-medium">{issue.title}</span>
                    <span className="text-muted-foreground block font-mono text-xs">
                      {issue.rule_id}
                    </span>
                  </TableCell>
                  <TableCell className="text-muted-foreground hidden text-sm md:table-cell">
                    {CATEGORY_LABELS[issue.category]}
                  </TableCell>
                  <TableCell className="text-muted-foreground hidden font-mono text-xs lg:table-cell">
                    {issue.file_path ? (
                      <span className="break-all">
                        {issue.file_path}
                        {issue.line_start !== null ? `:${issue.line_start}` : ""}
                      </span>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
