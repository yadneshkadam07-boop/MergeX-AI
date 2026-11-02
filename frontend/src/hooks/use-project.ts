import { useOutletContext } from "react-router-dom";
import type { Project } from "@/types/project";

export interface ProjectContextType {
  project: Project;
  refreshProject: () => Promise<void>;
}

export function useProject() {
  return useOutletContext<ProjectContextType>();
}
