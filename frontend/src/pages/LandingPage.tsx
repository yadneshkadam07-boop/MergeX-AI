import { BackendStatus } from "@/components/BackendStatus";

/**
 * Placeholder shell for the landing page.
 *
 * Phase 5 replaces this with the real import form (GitHub URL / ZIP upload).
 * For now it exists to prove the full stack is wired: React renders, Tailwind
 * tokens resolve, TanStack Query reaches the FastAPI health endpoint.
 */
export function LandingPage() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-3xl flex-col justify-center gap-6 px-4 py-16">
      <BackendStatus />

      <div className="space-y-4">
        <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">MergeX AI</h1>
        <p className="text-muted-foreground max-w-prose text-lg">
          Import a repository and find out whether its frontend, backend and database actually work
          together — not whether each layer looks fine on its own.
        </p>
      </div>

      <dl className="border-border grid gap-4 rounded-xl border p-5 sm:grid-cols-3">
        {[
          ["API contracts", "Frontend calls vs. backend routes"],
          ["Schema drift", "ORM models vs. database schema"],
          ["Security", "Secrets, auth gaps, CORS, CVEs"],
        ].map(([term, description]) => (
          <div key={term} className="space-y-1">
            <dt className="text-sm font-medium">{term}</dt>
            <dd className="text-muted-foreground text-sm">{description}</dd>
          </div>
        ))}
      </dl>

      <p className="text-muted-foreground text-sm">
        Scaffold build (Phase 0). The import flow, analysis pipeline and dashboard arrive in later
        phases.
      </p>
    </main>
  );
}
