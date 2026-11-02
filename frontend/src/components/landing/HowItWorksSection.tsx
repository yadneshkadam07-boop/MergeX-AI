import { Card, CardContent } from "@/components/ui/card";
import { landingContent } from "@/content/landing";

export function HowItWorksSection() {
  const { howItWorks } = landingContent;

  return (
    <section id="how-it-works" className="bg-muted/20 scroll-mt-20 border-t py-20">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <span className="text-primary text-xs font-semibold tracking-wider uppercase">
            {howItWorks.tagline}
          </span>
          <h2 className="text-foreground mt-2 text-3xl font-bold tracking-tight sm:text-4xl">
            {howItWorks.title}
          </h2>
          <p className="text-muted-foreground mt-3 text-base leading-relaxed">
            {howItWorks.description}
          </p>
        </div>

        <div className="mt-16 grid grid-cols-1 gap-6 md:grid-cols-4">
          {howItWorks.steps.map((step) => (
            <Card key={step.step} interactive className="group bg-card h-full border p-6">
              <CardContent className="flex flex-col items-start gap-4 p-0">
                {/* Step indicator */}
                <div className="bg-background text-foreground ring-background group-hover:border-primary group-hover:text-primary flex size-10 items-center justify-center rounded-full border font-mono text-sm font-bold shadow-xs ring-4 transition-colors">
                  0{step.step}
                </div>

                <div className="space-y-2">
                  <h3 className="text-foreground flex items-center gap-1.5 text-base font-semibold">
                    {step.title}
                  </h3>
                  <p className="text-muted-foreground text-sm leading-relaxed">
                    {step.description}
                  </p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
