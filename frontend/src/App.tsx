import { Route, Routes } from "react-router-dom";

import { TooltipProvider } from "@/components/ui/tooltip";
import { AnalysisPage } from "@/pages/AnalysisPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { LandingPage } from "@/pages/LandingPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

/**
 * Route table.
 *
 * An analysis has two views: the live run and the finished report. They are
 * separate routes rather than one page that changes shape, so a report can
 * be linked to and reloaded without re-entering a "watching" state.
 */
export default function App() {
  return (
    <TooltipProvider delayDuration={200}>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/analyses/:analysisId" element={<AnalysisPage />} />
        <Route path="/analyses/:analysisId/report" element={<DashboardPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </TooltipProvider>
  );
}
