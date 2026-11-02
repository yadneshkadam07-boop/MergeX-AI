import type { IssueSeverity } from "@/types/project";

export interface UserSettings {
  displayName: string;
  email: string;
  theme: "light" | "dark" | "system";
  githubConnected: boolean;
  githubUsername?: string | undefined;
  checks: {
    integration: boolean;
    security: boolean;
    dependencies: boolean;
    deployment: boolean;
  };
  alertSeverity: IssueSeverity;
}
