import { useState } from "react";
import { Link, Outlet } from "react-router-dom";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Menu } from "lucide-react";

export function PublicLayout() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <div className="bg-background text-foreground flex min-h-screen flex-col">
      {/* Skip to Main Content Link for Keyboard and Screen Reader Users */}
      <a
        href="#main-content"
        className="focus:bg-primary focus:text-primary-foreground focus:ring-ring sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-md focus:px-4 focus:py-2 focus:text-xs focus:font-semibold focus:shadow-lg focus:ring-2"
      >
        Skip to main content
      </a>

      {/* Top Navbar */}
      <header className="bg-background/80 sticky top-0 z-40 border-b backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-7xl min-w-0 items-center justify-between px-4 sm:px-6 lg:px-8">
          {/* Left: Logo Placeholder */}
          <Link to="/" className="flex shrink-0 items-center">
            <Logo size="md" />
          </Link>

          {/* Desktop Right Links */}
          <div className="hidden shrink-0 items-center gap-6 md:flex">
            <a
              href="#features"
              className="text-muted-foreground hover:text-foreground text-sm font-medium transition-colors"
            >
              Features
            </a>
            <a
              href="#how-it-works"
              className="text-muted-foreground hover:text-foreground text-sm font-medium transition-colors"
            >
              How it works
            </a>
            <div className="bg-border h-4 w-px" />
            <ThemeToggle />
            <Button asChild size="sm">
              <Link to="/login">Log in</Link>
            </Button>
          </div>

          {/* Mobile Right Controls */}
          <div className="flex shrink-0 items-center gap-2 md:hidden">
            <ThemeToggle />
            <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
              <SheetTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-9"
                  aria-label="Open mobile menu"
                >
                  <Menu className="size-5" />
                </Button>
              </SheetTrigger>
              <SheetContent side="right" className="w-72">
                <SheetHeader>
                  <SheetTitle className="text-left font-bold">MergeX AI</SheetTitle>
                </SheetHeader>
                <div className="mt-6 flex flex-col gap-4">
                  <a
                    href="#features"
                    onClick={() => setMobileMenuOpen(false)}
                    className="text-muted-foreground hover:bg-muted hover:text-foreground rounded-md px-3 py-2 text-base font-medium transition-colors"
                  >
                    Features
                  </a>
                  <a
                    href="#how-it-works"
                    onClick={() => setMobileMenuOpen(false)}
                    className="text-muted-foreground hover:bg-muted hover:text-foreground rounded-md px-3 py-2 text-base font-medium transition-colors"
                  >
                    How it works
                  </a>
                  <hr className="border-border my-2" />
                  <Button asChild className="w-full" onClick={() => setMobileMenuOpen(false)}>
                    <Link to="/login">Log in</Link>
                  </Button>
                </div>
              </SheetContent>
            </Sheet>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main id="main-content" tabIndex={-1} className="flex-1 focus:outline-hidden">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <Outlet />
        </div>
      </main>

      {/* Footer Placeholder */}
      <footer className="bg-muted/30 text-muted-foreground border-t py-8 text-center text-xs">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-4 sm:flex-row sm:px-6 lg:px-8">
          <p>
            © {new Date().getFullYear()} MergeX AI. Multi-agent code validation & deployment
            platform.
          </p>
          <div className="flex gap-6">
            <a href="#privacy" className="hover:underline">
              Privacy
            </a>
            <a href="#terms" className="hover:underline">
              Terms
            </a>
            <a href="#docs" className="hover:underline">
              Docs
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
