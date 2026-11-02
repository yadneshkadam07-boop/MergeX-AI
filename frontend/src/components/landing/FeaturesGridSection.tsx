import React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { landingContent, type FeatureItem } from "@/content/landing";
import { FeatureIcon } from "@/components/landing/FeatureIcon";
import { FolderGit2, Layers, FileCode, ShieldAlert, GitFork, Wand2 } from "lucide-react";

const ICON_MAP: Record<
  FeatureItem["iconName"],
  React.ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" | "false" }>
> = {
  FolderGit2,
  Layers,
  FileCode,
  ShieldAlert,
  GitFork,
  Wand2,
};

export function FeaturesGridSection() {
  const { features } = landingContent;

  return (
    <section id="features" className="scroll-mt-20 py-20">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <span className="text-primary text-xs font-semibold tracking-wider uppercase">
            Platform Capabilities
          </span>
          <h2 className="text-foreground mt-2 text-3xl font-bold tracking-tight sm:text-4xl">
            Complete architectural inspection
          </h2>
          <p className="text-muted-foreground mt-3 text-base">
            Everything needed to audit and align disparate components generated across multiple
            prompts and AI coding tools.
          </p>
        </div>

        <div className="mt-14 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((feature) => (
            <Card key={feature.id} interactive className="group bg-card border">
              <CardHeader className="pb-3">
                <div className="flex items-center gap-3">
                  <FeatureIcon icon={ICON_MAP[feature.iconName]} tone={feature.tone} />
                  <CardTitle className="group-hover:text-primary text-base font-semibold transition-colors">
                    {feature.title}
                  </CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-muted-foreground text-sm leading-relaxed">
                  {feature.description}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
