import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { FileQuestion, Home, ArrowLeft } from "lucide-react";
import { useDocumentTitle } from "@/hooks/use-document-title";

export function NotFoundPage() {
  useDocumentTitle("Page Not Found");

  return (
    <div className="flex min-h-[calc(100vh-8rem)] flex-col items-center justify-center px-4 text-center">
      <div className="bg-muted text-muted-foreground flex size-16 items-center justify-center rounded-2xl shadow-xs">
        <FileQuestion className="size-8" />
      </div>

      <span className="text-muted-foreground mt-6 font-mono text-sm font-semibold tracking-wider uppercase">
        404 Error
      </span>
      <h1 className="text-foreground mt-2 text-3xl font-bold tracking-tight sm:text-4xl">
        Page Not Found
      </h1>
      <p className="text-muted-foreground mt-3 max-w-md text-sm">
        The page you are looking for doesn't exist, has been moved, or belongs to a different route.
      </p>

      <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
        <Button asChild variant="default" className="gap-2 text-xs font-semibold">
          <Link to="/dashboard">
            <Home className="size-4" /> Back to Dashboard
          </Link>
        </Button>
        <Button
          type="button"
          variant="outline"
          className="gap-2 text-xs font-semibold"
          onClick={() => window.history.back()}
        >
          <ArrowLeft className="size-4" /> Go Back
        </Button>
      </div>
    </div>
  );
}
