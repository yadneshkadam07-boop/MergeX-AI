import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ButtonRow } from "@/components/ui/button-row";
import { ArrowRight, ChevronDown, Sparkles } from "lucide-react";
import { landingContent } from "@/content/landing";
import { ProductPreview } from "@/components/landing/ProductPreview";

export function HeroSection() {
  const { hero } = landingContent;

  const scrollToHowItWorks = () => {
    const el = document.getElementById("how-it-works");
    if (el) {
      el.scrollIntoView({ behavior: "smooth" });
    }
  };

  return (
    <section className="relative overflow-hidden py-12 md:py-20 lg:py-24">
      {/* Soft radial glow behind the headline */}
      <div
        aria-hidden="true"
        className="bg-plum-200/60 dark:bg-plum-600/20 pointer-events-none absolute -top-20 -left-20 -z-10 h-[480px] w-[560px] rounded-full blur-3xl"
      />

      <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-12 lg:gap-8">
        {/* Left Column: Headlines & Actions */}
        <div className="flex flex-col items-start text-left lg:col-span-7">
          <div className="bg-muted/60 text-muted-foreground inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium backdrop-blur-sm">
            <Sparkles className="text-primary size-3.5" />
            <span>{hero.badge}</span>
          </div>

          <h1 className="text-foreground mt-6 text-4xl font-extrabold tracking-tight sm:text-5xl sm:leading-[1.15] lg:text-6xl">
            Ship AI-generated code{" "}
            <span className="from-plum-600 to-plum-400 dark:from-plum-300 dark:to-plum-100 bg-gradient-to-r bg-clip-text text-transparent">
              with confidence.
            </span>
          </h1>

          <p className="text-muted-foreground mt-6 max-w-xl text-base sm:text-lg sm:leading-relaxed">
            {hero.subheadline}
          </p>

          <ButtonRow stackOnMobile className="mt-8 gap-4">
            <Button
              asChild
              size="lg"
              className="from-evergreen-700 to-evergreen-500 hover:from-evergreen-800 hover:to-evergreen-600 text-milk-100 min-h-11 w-full bg-gradient-to-r px-6 font-semibold shadow-xs sm:w-auto"
            >
              <Link to="/login" className="flex items-center justify-center gap-2">
                <span>{hero.primaryCta}</span>
                <ArrowRight className="size-4" />
              </Link>
            </Button>

            <Button
              variant="outline"
              size="lg"
              onClick={scrollToHowItWorks}
              className="text-foreground hover:bg-muted min-h-11 w-full px-6 font-medium sm:w-auto"
            >
              <span>{hero.secondaryCta}</span>
              <ChevronDown className="ml-2 size-4 opacity-70" />
            </Button>
          </ButtonRow>

          {/* Trust bullet info */}
          <div className="text-muted-foreground mt-10 flex flex-wrap items-center gap-4 border-t pt-6 text-xs sm:gap-6">
            <div className="flex items-center gap-2">
              <span className="bg-success flex size-2 rounded-full" />
              <span>Full AST & Schema Inspection</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="bg-brand-secondary flex size-2 rounded-full" />
              <span>Zero Production Access Required</span>
            </div>
          </div>
        </div>

        {/* Right Column: Interactive/Static Product Mock */}
        <div className="flex justify-center lg:col-span-5 lg:justify-end">
          <ProductPreview />
        </div>
      </div>
    </section>
  );
}
