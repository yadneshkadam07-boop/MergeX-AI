import { HeroSection } from "@/components/landing/HeroSection";
import { ProblemStripSection } from "@/components/landing/ProblemStripSection";
import { FeaturesGridSection } from "@/components/landing/FeaturesGridSection";
import { HowItWorksSection } from "@/components/landing/HowItWorksSection";
import { ToolsSection } from "@/components/landing/ToolsSection";
import { FinalCtaSection } from "@/components/landing/FinalCtaSection";
import { useDocumentTitle } from "@/hooks/use-document-title";

export function Landing() {
  useDocumentTitle("Multi-Agent Code Diagnostics & Validation");
  return (
    <div className="flex flex-col">
      {/* 1. Hero (with integrated 3. Product preview card) */}
      <HeroSection />

      {/* 2. Problem strip */}
      <ProblemStripSection />

      {/* 4. Features grid (id="features") */}
      <FeaturesGridSection />

      {/* 5. How it works (id="how-it-works") */}
      <HowItWorksSection />

      {/* 6. Works with your AI tools */}
      <ToolsSection />

      {/* 7. Final CTA */}
      <FinalCtaSection />
    </div>
  );
}
