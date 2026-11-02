import type {
  CategoryScores,
  IssueCounts,
  PriorityIssue,
  ScanMeta,
  SeverityCounts,
} from "@/types/project";

const CANDIDATE_ISSUES: PriorityIssue[] = [
  {
    id: "iss-1",
    title: "Frontend calls /api/users but backend exposes /api/user",
    category: "integration",
    severity: "critical",
    filePath: "frontend/src/api/users.ts:18",
    shortDescription: "Endpoint path contract mismatch causes HTTP 404 in user directory views.",
  },
  {
    id: "iss-2",
    title: "Missing foreign key on orders.user_id",
    category: "integration",
    severity: "high",
    filePath: "backend/alembic/versions/20240912_create_orders.py:24",
    shortDescription:
      "Relational integrity constraint missing, permitting orphaned purchase records.",
  },
  {
    id: "iss-3",
    title: "Hardcoded API key in config.js",
    category: "security",
    severity: "critical",
    filePath: "backend/src/config/runtime.js:42",
    shortDescription: "Sensitive third-party service credential committed directly in source code.",
  },
  {
    id: "iss-4",
    title: "CORS allows all origins in production",
    category: "security",
    severity: "high",
    filePath: "backend/src/main.py:31",
    shortDescription: "Wildcard origin configuration permits cross-site request forgery risks.",
  },
  {
    id: "iss-5",
    title: "Outdated package with known high-severity CVE",
    category: "dependencies",
    severity: "high",
    filePath: "package.json:28",
    shortDescription: "Vulnerable transitive dependency allows prototype pollution exploits.",
  },
  {
    id: "iss-6",
    title: "Missing environment variable DATABASE_URL in deploy config",
    category: "deployment",
    severity: "critical",
    filePath: "docker-compose.prod.yml:14",
    shortDescription: "Service startup crashes when required database connection URI is undefined.",
  },
  {
    id: "iss-7",
    title: "Unpinned base Docker image tag using latest",
    category: "deployment",
    severity: "medium",
    filePath: "Dockerfile:1",
    shortDescription: "Floating base image tag undermines deterministic container rebuilds.",
  },
  {
    id: "iss-8",
    title: "Unbounded query parameter in search route",
    category: "integration",
    severity: "medium",
    filePath: "backend/api/search.py:55",
    shortDescription: "Missing pagination limits allow unbounded memory consumption.",
  },
  {
    id: "iss-9",
    title: "Deprecated crypto algorithm used in session helper",
    category: "security",
    severity: "medium",
    filePath: "backend/utils/auth.py:89",
    shortDescription: "Legacy hash routine fails compliance with current TLS crypto guidelines.",
  },
  {
    id: "iss-10",
    title: "Missing HTTP health check probe definition",
    category: "deployment",
    severity: "low",
    filePath: "render.yaml:12",
    shortDescription:
      "Orchestrator readiness check defaults to TCP socket ping instead of HTTP /health.",
  },
];

/**
 * Generates consistent, realistic project details (category scores, severity counts,
 * top issues, and scan metadata) based on an overall health score.
 */
export function generateProjectDetails(score: number): {
  categoryScores: CategoryScores;
  severityCounts: SeverityCounts;
  issueCounts: IssueCounts;
  topIssues: PriorityIssue[];
  scanMeta: ScanMeta;
} {
  // Clamp score
  const clamped = Math.max(0, Math.min(100, Math.round(score)));

  // Generate category scores roughly consistent with healthScore (+/- random delta)
  const perturb = (base: number, maxDelta = 8) => {
    const delta = Math.floor(Math.random() * (maxDelta * 2 + 1)) - maxDelta;
    return Math.max(10, Math.min(100, base + delta));
  };

  const categoryScores: CategoryScores = {
    integration: perturb(clamped, 7),
    security: perturb(clamped, 9),
    dependencies: perturb(clamped, 6),
    deployment: perturb(clamped, 8),
  };

  // Severity counts scaling inversely with score
  let critical: number;
  let high: number;
  let medium: number;
  let low: number;

  if (clamped >= 85) {
    critical = 0;
    high = Math.random() > 0.6 ? 1 : 0;
    medium = Math.floor(Math.random() * 2) + 1;
    low = Math.floor(Math.random() * 3) + 1;
  } else if (clamped >= 70) {
    critical = Math.random() > 0.7 ? 1 : 0;
    high = Math.floor(Math.random() * 2) + 1;
    medium = Math.floor(Math.random() * 3) + 2;
    low = Math.floor(Math.random() * 3) + 2;
  } else if (clamped >= 50) {
    critical = Math.floor(Math.random() * 2) + 1;
    high = Math.floor(Math.random() * 3) + 2;
    medium = Math.floor(Math.random() * 4) + 2;
    low = Math.floor(Math.random() * 3) + 1;
  } else {
    critical = Math.floor(Math.random() * 3) + 2;
    high = Math.floor(Math.random() * 4) + 3;
    medium = Math.floor(Math.random() * 4) + 3;
    low = Math.floor(Math.random() * 3) + 2;
  }

  const severityCounts: SeverityCounts = { critical, high, medium, low };

  // Calculate issue counts per category
  const totalSeverity = critical + high + medium + low;
  const issueCounts: IssueCounts = {
    integration: Math.max(0, Math.round(totalSeverity * 0.35)),
    security: Math.max(0, Math.round(totalSeverity * 0.25)),
    dependencies: Math.max(0, Math.round(totalSeverity * 0.25)),
    deployment: Math.max(0, Math.round(totalSeverity * 0.15)),
  };

  // Select top issues matching the severity profile
  let candidatePool = [...CANDIDATE_ISSUES];
  if (critical === 0) {
    candidatePool = candidatePool.filter((i) => i.severity !== "critical");
  }
  if (high === 0) {
    candidatePool = candidatePool.filter((i) => i.severity !== "high");
  }

  // Shuffle and pick 3 to 5 items
  const count = Math.min(
    candidatePool.length,
    Math.max(1, Math.min(5, Math.floor(totalSeverity / 2) + 1)),
  );
  const shuffled = [...candidatePool].sort(() => 0.5 - Math.random());
  const topIssues = shuffled.slice(0, count);

  // Generate deterministic/clean scan meta
  const randomSha = Math.random().toString(16).substring(2, 9);
  const scanMeta: ScanMeta = {
    branch: "main",
    commitSha: randomSha,
    durationSeconds: Math.floor(Math.random() * 18) + 12,
    filesScanned: Math.floor(Math.random() * 120) + 48,
    agentsRun: 6,
  };

  return {
    categoryScores,
    severityCounts,
    issueCounts,
    topIssues,
    scanMeta,
  };
}
