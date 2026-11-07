import { lazy, Suspense, useEffect } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { LoadingState } from "@/components/shared/LoadingState";

import { PublicLayout } from "@/layouts/PublicLayout";
import { AppLayout } from "@/layouts/AppLayout";
import { ProjectLayout } from "@/layouts/ProjectLayout";
import { AuthProvider } from "@/contexts/AuthContext";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";

// Code-split pages for high performance and reduced initial bundle
const Landing = lazy(() => import("@/pages/Landing").then((m) => ({ default: m.Landing })));
const Login = lazy(() => import("@/pages/Login").then((m) => ({ default: m.Login })));
const AuthCallback = lazy(() =>
  import("@/pages/AuthCallback").then((m) => ({ default: m.AuthCallback })),
);
const Dashboard = lazy(() => import("@/pages/Dashboard").then((m) => ({ default: m.Dashboard })));
const NewAnalysis = lazy(() =>
  import("@/pages/NewAnalysis").then((m) => ({ default: m.NewAnalysis })),
);
const Settings = lazy(() => import("@/pages/Settings").then((m) => ({ default: m.Settings })));
const NotFoundPage = lazy(() =>
  import("@/pages/NotFoundPage").then((m) => ({ default: m.NotFoundPage })),
);

// Project Sub-pages (Architecture and Docs loaded strictly on demand)
const ProjectOverview = lazy(() =>
  import("@/pages/ProjectOverview").then((m) => ({ default: m.ProjectOverview })),
);
const ProjectIntegration = lazy(() =>
  import("@/pages/ProjectIntegration").then((m) => ({ default: m.ProjectIntegration })),
);
const ProjectSecurity = lazy(() =>
  import("@/pages/ProjectSecurity").then((m) => ({ default: m.ProjectSecurity })),
);
const ProjectDependencies = lazy(() =>
  import("@/pages/ProjectDependencies").then((m) => ({ default: m.ProjectDependencies })),
);
const ProjectDeploy = lazy(() =>
  import("@/pages/ProjectDeploy").then((m) => ({ default: m.ProjectDeploy })),
);
const ProjectArchitecture = lazy(() =>
  import("@/pages/ProjectArchitecture").then((m) => ({ default: m.ProjectArchitecture })),
);
const ProjectDocs = lazy(() =>
  import("@/pages/ProjectDocs").then((m) => ({ default: m.ProjectDocs })),
);

function RouteChangeHandler() {
  const { pathname } = useLocation();

  useEffect(() => {
    window.scrollTo(0, 0);
    // Accessibility: shift focus to page title or main landmark on navigation
    const target = document.querySelector<HTMLElement>("main h1, #main-content");
    if (target) {
      target.focus({ preventScroll: true });
    }
  }, [pathname]);

  return null;
}

export default function App() {
  useEffect(() => {
    // Non-blocking pre-warm ping for cold start hosting (e.g. Render free tier)
    try {
      fetch("/api/health").catch(() => {});
    } catch {
      // Ignore background wake errors
    }
  }, []);

  return (
    <ErrorBoundary>
      <AuthProvider>
        <TooltipProvider delayDuration={200}>
          <RouteChangeHandler />
          <Suspense fallback={<LoadingState className="my-12" minHeight="min-h-[400px]" />}>
            <Routes>
              {/* Public Routes (inside PublicLayout) */}
              <Route element={<PublicLayout />}>
                <Route path="/" element={<Landing />} />
                <Route path="/login" element={<Login />} />
                <Route path="/login/callback" element={<AuthCallback />} />
              </Route>

              {/* Protected App Shell Routes (inside ProtectedRoute + AppLayout) */}
              <Route element={<ProtectedRoute />}>
                <Route element={<AppLayout />}>
                  <Route path="/dashboard" element={<Dashboard />} />
                  <Route path="/analyze" element={<NewAnalysis />} />
                  <Route path="/settings" element={<Settings />} />

                  {/* Nested /project/:id routes under ProjectLayout */}
                  <Route path="/project/:id" element={<ProjectLayout />}>
                    <Route index element={<ProjectOverview />} />
                    <Route path="integration" element={<ProjectIntegration />} />
                    <Route path="security" element={<ProjectSecurity />} />
                    <Route path="dependencies" element={<ProjectDependencies />} />
                    <Route path="deploy" element={<ProjectDeploy />} />
                    <Route path="architecture" element={<ProjectArchitecture />} />
                    <Route path="docs" element={<ProjectDocs />} />
                  </Route>
                </Route>
              </Route>

              {/* 404 Catch-All */}
              <Route path="*" element={<NotFoundPage />} />
            </Routes>
          </Suspense>
          <Toaster position="bottom-right" richColors closeButton />
        </TooltipProvider>
      </AuthProvider>
    </ErrorBoundary>
  );
}
