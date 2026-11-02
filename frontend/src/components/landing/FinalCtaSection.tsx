import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { landingContent } from "@/content/landing";
import { ArrowRight, ShieldCheck } from "lucide-react";

export function FinalCtaSection() {
  const { finalCta } = landingContent;

  return (
    <section className="bg-muted/40 border-t py-20">
      <div className="mx-auto max-w-5xl px-4 text-center sm:px-6 lg:px-8">
        <div className="bg-primary/10 text-primary mx-auto flex size-12 items-center justify-center rounded-2xl">
          <ShieldCheck className="size-6" />
        </div>

        <h2 className="text-foreground mt-6 text-3xl font-extrabold tracking-tight sm:text-4xl">
          {finalCta.title}
        </h2>

        <p className="text-muted-foreground mx-auto mt-4 max-w-xl text-base leading-relaxed">
          {finalCta.description}
        </p>

        <div className="mt-8 flex justify-center">
          <Button asChild size="lg" className="h-auto min-h-11 px-8 py-3 font-semibold shadow-md">
            <Link to="/login" className="flex items-center gap-2">
              <span>{finalCta.buttonText}</span>
              <ArrowRight className="size-4" />
            </Link>
          </Button>
        </div>
      </div>
    </section>
  );
}
