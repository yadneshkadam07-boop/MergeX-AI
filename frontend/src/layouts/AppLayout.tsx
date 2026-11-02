import { useState, useMemo, useRef, useEffect } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { OfflineBanner } from "@/components/shared/OfflineBanner";
import { cn } from "@/lib/utils";
import {
  ChevronLeft,
  ChevronRight,
  FolderGit2,
  LayoutDashboard,
  LogOut,
  Menu,
  PlusCircle,
  Settings,
  User,
} from "lucide-react";
import { useAuth } from "@/hooks/use-auth";

const NAV_ITEMS = [
  {
    name: "Dashboard",
    to: "/dashboard",
    icon: LayoutDashboard,
  },
  {
    name: "New analysis",
    to: "/analyze",
    icon: PlusCircle,
  },
  {
    name: "Settings",
    to: "/settings",
    icon: Settings,
  },
];

export function AppLayout() {
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [userDropdownOpen, setUserDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const location = useLocation();

  // Close user dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setUserDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Compute page title based on current path
  const pageTitle = useMemo(() => {
    const path = location.pathname;
    if (path.startsWith("/dashboard")) return "Dashboard";
    if (path.startsWith("/analyze")) return "New Analysis";
    if (path.startsWith("/settings")) return "Settings";
    if (path.startsWith("/project/")) {
      const parts = path.split("/").filter(Boolean);
      const projectId = parts[1] || "";
      const sub = parts[2]
        ? ` / ${parts[2].charAt(0).toUpperCase() + parts[2].slice(1)}`
        : " / Overview";
      return `Project: ${projectId}${sub}`;
    }
    return "MergeX AI";
  }, [location.pathname]);

  const SidebarContent = ({ onNavigate }: { onNavigate?: () => void }) => (
    <div className="flex h-full flex-col justify-between">
      <div>
        {/* Wordmark */}
        <div className="flex h-16 items-center gap-3 border-b px-4">
          <Link
            to="/dashboard"
            onClick={onNavigate}
            className="text-foreground flex items-center gap-2.5 overflow-hidden font-bold tracking-tight"
          >
            <span className="bg-primary text-primary-foreground flex size-8 shrink-0 items-center justify-center rounded-lg text-xs font-black shadow-xs">
              M
            </span>
            {(!collapsed || onNavigate) && (
              <span className="truncate text-base font-bold tracking-tight">MergeX AI</span>
            )}
          </Link>
        </div>

        {/* Navigation links */}
        <nav className="space-y-1.5 p-3">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={onNavigate}
                title={collapsed ? item.name : undefined}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-primary text-primary-foreground font-semibold shadow-xs"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                    collapsed && !onNavigate && "justify-center px-2",
                  )
                }
              >
                <Icon className="size-4 shrink-0" />
                {(!collapsed || onNavigate) && <span className="truncate">{item.name}</span>}
              </NavLink>
            );
          })}
        </nav>
      </div>

      {/* Sidebar Footer Info */}
      {(!collapsed || onNavigate) && (
        <div className="text-muted-foreground border-t p-4 text-xs">
          <div className="flex items-center gap-2">
            <FolderGit2 className="text-muted-foreground size-4" />
            <span className="truncate font-mono">v0.1.0-stage1</span>
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div className="bg-background text-foreground flex min-h-screen flex-col">
      {/* Skip to Main Content Link for Keyboard and Screen Reader Users */}
      <a
        href="#main-content"
        className="focus:bg-primary focus:text-primary-foreground focus:ring-ring sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-md focus:px-4 focus:py-2 focus:text-xs focus:font-semibold focus:shadow-lg focus:ring-2"
      >
        Skip to main content
      </a>

      {/* Offline status indicator */}
      <OfflineBanner />

      <div className="flex flex-1 overflow-hidden">
        {/* Desktop Fixed Sidebar */}
        <aside
          className={cn(
            "bg-card z-30 hidden flex-col border-r transition-all duration-200 md:flex",
            collapsed ? "w-16" : "w-64",
          )}
        >
          <SidebarContent />
        </aside>

        {/* Mobile Drawer Sidebar */}
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetContent side="left" className="w-64 p-0">
            <SheetHeader className="sr-only">
              <SheetTitle>Navigation Menu</SheetTitle>
            </SheetHeader>
            <SidebarContent onNavigate={() => setMobileOpen(false)} />
          </SheetContent>
        </Sheet>

        {/* Main Container */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Top Bar */}
          <header className="bg-background/80 sticky top-0 z-20 flex h-16 shrink-0 items-center justify-between border-b px-4 backdrop-blur-md sm:px-6">
            {/* Left: Sidebar Toggle & Page Title */}
            <div className="flex min-w-0 flex-1 items-center gap-2 sm:gap-3">
              {/* Mobile Hamburger */}
              <Button
                variant="ghost"
                size="icon"
                className="size-9 shrink-0 md:hidden"
                onClick={() => setMobileOpen(true)}
                aria-label="Open sidebar"
              >
                <Menu className="size-5" />
              </Button>

              {/* Desktop Collapse Toggle */}
              <Button
                variant="ghost"
                size="icon"
                className="text-muted-foreground hover:text-foreground hidden size-9 shrink-0 md:inline-flex"
                onClick={() => setCollapsed(!collapsed)}
                title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              >
                {collapsed ? (
                  <ChevronRight className="size-4" />
                ) : (
                  <ChevronLeft className="size-4" />
                )}
              </Button>

              <div className="bg-border hidden h-4 w-px shrink-0 sm:block" />

              <h2 className="text-foreground min-w-0 flex-1 truncate text-sm font-semibold tracking-tight sm:text-base">
                {pageTitle}
              </h2>
            </div>

            {/* Right: Theme Toggle & User Dropdown */}
            <div className="flex shrink-0 items-center gap-2">
              <ThemeToggle />

              {/* User Dropdown */}
              <div className="relative" ref={dropdownRef}>
                <button
                  type="button"
                  onClick={() => setUserDropdownOpen(!userDropdownOpen)}
                  className="bg-muted text-foreground hover:bg-muted/80 focus:ring-ring flex size-9 items-center justify-center overflow-hidden rounded-full border transition-colors focus:ring-2 focus:outline-hidden"
                  aria-expanded={userDropdownOpen}
                  aria-label="User menu"
                >
                  {user?.avatarUrl ? (
                    <img
                      src={user.avatarUrl}
                      alt={user.name || "User avatar"}
                      className="size-full rounded-full object-cover"
                    />
                  ) : (
                    <User className="size-4" />
                  )}
                </button>

                {userDropdownOpen && (
                  <div className="bg-popover text-popover-foreground animate-in fade-in-0 zoom-in-95 absolute right-0 z-50 mt-2 w-52 rounded-md border p-1 shadow-md">
                    <div className="border-b px-3 py-2 text-xs">
                      <p className="text-foreground truncate font-semibold">
                        {user?.name || "MergeX Developer"}
                      </p>
                      <p className="text-muted-foreground truncate">
                        {user?.email || "developer@mergex.ai"}
                      </p>
                    </div>

                    <Link
                      to="/settings"
                      onClick={() => setUserDropdownOpen(false)}
                      className="text-foreground hover:bg-accent hover:text-accent-foreground flex w-full items-center gap-2 rounded-sm px-2.5 py-1.5 text-xs transition-colors"
                    >
                      <Settings className="size-3.5" />
                      Settings
                    </Link>

                    <button
                      type="button"
                      onClick={() => {
                        setUserDropdownOpen(false);
                        logout();
                      }}
                      className="text-destructive hover:bg-destructive/10 flex w-full items-center gap-2 rounded-sm px-2.5 py-1.5 text-xs transition-colors"
                    >
                      <LogOut className="size-3.5" />
                      Log out
                    </button>
                  </div>
                )}
              </div>
            </div>
          </header>

          {/* Scrollable Main Content */}
          <main
            id="main-content"
            tabIndex={-1}
            className="flex-1 overflow-y-auto p-4 focus:outline-hidden sm:p-6 lg:p-8"
          >
            <div className="mx-auto max-w-6xl">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}
