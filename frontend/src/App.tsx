import { Route, Routes } from "react-router-dom";

import { LandingPage } from "@/pages/LandingPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

/**
 * Route table.
 *
 * Later phases add `/analyses/:id` (live progress) and `/projects/:id`
 * (dashboard, issues, architecture graph).
 */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
