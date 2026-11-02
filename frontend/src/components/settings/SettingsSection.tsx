import React from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface SettingsSectionProps {
  title: string;
  description: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
}

export function SettingsSection({
  title,
  description,
  children,
  footer,
  className,
}: SettingsSectionProps) {
  return (
    <Card className={cn("bg-card border shadow-xs", className)}>
      <CardHeader className="border-b p-6 pb-4">
        <CardTitle className="text-foreground text-base font-bold">{title}</CardTitle>
        <CardDescription className="text-muted-foreground mt-0.5 text-xs leading-relaxed">
          {description}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 p-6">{children}</CardContent>
      {footer && (
        <div className="bg-muted/20 flex items-center justify-between rounded-b-xl border-t px-6 py-3 text-xs">
          {footer}
        </div>
      )}
    </Card>
  );
}
