import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-xl flex-col items-start justify-center gap-4 px-4">
      <p className="text-muted-foreground font-mono text-sm">404</p>
      <h1 className="text-3xl font-semibold tracking-tight">Page not found</h1>
      <Link to="/" className="text-sm underline underline-offset-4">
        Back to the start
      </Link>
    </main>
  );
}
