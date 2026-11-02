import * as React from "react";
import { cn } from "@/lib/utils";

export interface ButtonRowProps extends React.HTMLAttributes<HTMLDivElement> {
  align?: "start" | "center" | "end" | "between";
  stackOnMobile?: boolean;
}

/**
 * Standardized responsive button row that wraps cleanly, prevents overflow
 * at high zoom levels, and optionally stacks buttons full-width on mobile.
 */
export function ButtonRow({
  className,
  align = "start",
  stackOnMobile = false,
  ...props
}: ButtonRowProps) {
  const alignClasses = {
    start: "justify-start",
    center: "justify-center",
    end: "justify-end",
    between: "justify-between",
  }[align];

  return (
    <div
      data-slot="button-row"
      className={cn(
        "flex flex-wrap gap-2 items-center min-w-0 max-w-full",
        alignClasses,
        stackOnMobile && "flex-col sm:flex-row sm:items-center [&>*]:w-full sm:[&>*]:w-auto",
        className
      )}
      {...props}
    />
  );
}
