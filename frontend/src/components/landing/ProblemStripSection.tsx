import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { landingContent } from "@/content/landing";
import { AlertCircle, Database, Unplug } from "lucide-react";

export function ProblemStripSection() {
  const { problemStrip } = landingContent;

  const getProblemIcon = (idx: number) => {
    switch (idx) {
      case 0:
        return <Unplug className="text-accent-foreground size-5" />;
      case 1:
        return <Database className="text-accent-foreground size-5" />;
      case 2:
      default:
        return <AlertCircle className="text-accent-foreground size-5" />;
    }
  };

  return (
    <section className="bg-muted/30 border-y py-16">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <span className="text-primary text-xs font-semibold tracking-wider uppercase">
            {problemStrip.tagline}
          </span>
          <h2 className="text-foreground mt-2 text-2xl font-bold tracking-tight sm:text-3xl">
            {problemStrip.title}
          </h2>
          <p className="text-muted-foreground mt-3 text-sm leading-relaxed">
            {problemStrip.description}
          </p>
        </div>

        <div className="mt-12 grid grid-cols-1 gap-6 sm:grid-cols-3">
          {problemStrip.cards.map((card, idx) => (
            <Card key={card.title} interactive className="bg-card/80 border">
              <CardHeader className="pb-2">
                <div className="flex items-center gap-3">
                  <div className="bg-accent text-accent-foreground flex size-9 items-center justify-center rounded-lg">
                    {getProblemIcon(idx)}
                  </div>
                  <CardTitle className="text-base leading-tight font-semibold">
                    {card.title}
                  </CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-muted-foreground text-sm leading-relaxed">{card.description}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
