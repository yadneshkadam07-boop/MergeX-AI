export interface ProblemCard {
  title: string;
  description: string;
}

export type FeatureTone = "evergreen" | "indigo" | "orchid" | "rose" | "sky" | "gold";

export interface FeatureItem {
  id: string;
  title: string;
  description: string;
  iconName: "FolderGit2" | "Layers" | "FileCode" | "ShieldAlert" | "GitFork" | "Wand2";
  tone: FeatureTone;
}

export interface WorkflowStep {
  step: number;
  title: string;
  description: string;
}

export interface CategoryStatus {
  name: string;
  status: "Passed" | "Warning" | "Critical";
  scoreText: string;
  details: string;
}

export const landingContent = {
  hero: {
    badge: "Multi-Agent Code Intelligence",
    headline: "Ship AI-generated code with confidence.",
    subheadline:
      "MergeX AI inspects your repositories for cross-stack integration issues, schema mismatches, security risks, and deployment readiness before code reaches production.",
    primaryCta: "Analyze a repo",
    secondaryCta: "See how it works",
  },

  problemStrip: {
    tagline: "The AI Code Synthesis Gap",
    title: "AI writes code in seconds. Connecting the pieces is on you.",
    description:
      "Autonomous coding agents generate frontend components, backend endpoints, and migrations in silos. Small drift causes silent runtime failures.",
    cards: [
      {
        title: "Frontend-backend mismatches",
        description:
          "API route drifts, mismatched payload types, and broken client fetch assumptions.",
      },
      {
        title: "Schema conflicts",
        description:
          "ORM model drift and desynchronized migrations that trigger runtime SQL exceptions.",
      },
      {
        title: "Hidden vulnerabilities",
        description:
          "Insecure dependencies, leaked API tokens, and missing authorization guards in agent code.",
      },
    ] as ProblemCard[],
  },

  productPreview: {
    projectName: "saas-starter-demo",
    branch: "main",
    score: 72,
    scoreMax: 100,
    scoreRating: "Needs Attention",
    lastAnalyzed: "Analyzed 2 mins ago",
    categories: [
      {
        name: "Integration",
        status: "Warning",
        scoreText: "68/100",
        details: "2 payload contract mismatches in /api/v1/auth",
      },
      {
        name: "Security",
        status: "Critical",
        scoreText: "54/100",
        details: "1 hardcoded secret token & 2 vulnerable libraries",
      },
      {
        name: "Dependencies",
        status: "Passed",
        scoreText: "95/100",
        details: "All licenses permissive, zero duplicate sub-trees",
      },
      {
        name: "Deployment",
        status: "Passed",
        scoreText: "88/100",
        details: "Dockerfile builds clean; health probe config verified",
      },
    ] as CategoryStatus[],
  },

  features: [
    {
      id: "github-import",
      title: "GitHub import",
      description:
        "One-click connection to public or private repos, PR branches, or local archives.",
      iconName: "FolderGit2",
      tone: "evergreen",
    },
    {
      id: "stack-detection",
      title: "Stack detection",
      description:
        "Automatically maps frameworks, databases, package managers, and runtime targets.",
      iconName: "Layers",
      tone: "indigo",
    },
    {
      id: "schema-validation",
      title: "API and schema validation",
      description:
        "Traces RPC/REST routes directly against frontend call sites and database schemas.",
      iconName: "FileCode",
      tone: "orchid",
    },
    {
      id: "security-scanning",
      title: "Security scanning",
      description: "Detects exposed secrets, unvalidated prompt injections, and CVE advisories.",
      iconName: "ShieldAlert",
      tone: "rose",
    },
    {
      id: "architecture-viz",
      title: "Architecture visualization",
      description:
        "Interactive graph showing service boundaries, call topologies, and data dependencies.",
      iconName: "GitFork",
      tone: "sky",
    },
    {
      id: "ai-fixes",
      title: "AI fix suggestions",
      description:
        "Targeted, verified code diffs ready to merge directly back into your pull requests.",
      iconName: "Wand2",
      tone: "gold",
    },
  ] as FeatureItem[],

  howItWorks: {
    tagline: "How It Works",
    title: "From repository to production-ready in four steps",
    description:
      "Multi-agent review agents run concurrently to inspect your full application architecture.",
    steps: [
      {
        step: 1,
        title: "Import repo",
        description: "Connect your GitHub repository or supply a repository branch to inspect.",
      },
      {
        step: 2,
        title: "Agents analyze",
        description:
          "Specialized agents dissect API contracts, AST graphs, DB models, and Dockerfiles.",
      },
      {
        step: 3,
        title: "Get health score",
        description:
          "Receive a holistic score (0-100) broken down by integration, security, and deployment.",
      },
      {
        step: 4,
        title: "Fix with AI suggestions",
        description: "Apply synthesized patch diffs and commit fixes straight to your codebase.",
      },
    ] as WorkflowStep[],
  },

  supportedTools: ["Copilot", "Cursor", "Claude Code", "Lovable", "Bolt"],

  finalCta: {
    title: "Ready to verify your AI-generated codebase?",
    description:
      "Stop chasing runtime surprises and start merging multi-agent code with complete certainty.",
    buttonText: "Get started",
  },
};
