import { describe, it, expect } from "vitest";
import { generateArchitecture } from "@/mock/architecture";
import type { Project } from "@/types/project";
import type { Issue } from "@/types/issue";

const mockProjectBase: Project = {
  id: "proj-1",
  name: "demo-project",
  owner: "test-user",
  repoUrl: "https://github.com/test-user/demo-project",
  stack: ["React", "Node.js", "Express", "PostgreSQL"],
  healthScore: 85,
  status: "completed",
  issueCounts: {
    integration: 1,
    security: 1,
    dependencies: 1,
    deployment: 0,
  },
  categoryScores: {
    integration: 90,
    security: 80,
    dependencies: 85,
    deployment: 85,
  },
  severityCounts: {
    critical: 0,
    high: 1,
    medium: 1,
    low: 1,
  },
  topIssues: [],
  scanMeta: {
    branch: "main",
    commitSha: "a1b2c3d",
    durationSeconds: 12,
    filesScanned: 45,
    agentsRun: 4,
  },
  lastScannedAt: new Date().toISOString(),
};

describe("generateArchitecture", () => {
  it("generates tailored architecture for Python Healthcare Chatbot", () => {
    const chatbotProject: Project = {
      ...mockProjectBase,
      id: "proj-chatbot",
      name: "Health-Care-Chatbot",
      repoUrl: "https://github.com/amberkakkar01/Health-Care-Chatbot",
      stack: ["Python", "Flask", "NLTK", "Keras"],
    };

    const issues: Issue[] = [
      {
        id: "iss-1",
        projectId: "proj-chatbot",
        category: "integration",
        severity: "critical",
        status: "open",
        title: "Chat route response mismatch",
        shortDescription: "Endpoint expects string but received JSON object",
        filePath: "app.py",
        explanation: "API route mismatch",
        impact: "Breaks chat response",
        suggestedFix: { summary: "Align response", steps: [] },
      },
    ];

    const result = generateArchitecture(chatbotProject, issues);

    const labels = result.nodes.map((n) => n.label);
    expect(labels).toContain("Chatbot Web Interface");
    expect(labels).toContain("Healthcare Dialogue Server");
    expect(labels).toContain("NLP Intent Engine");
    expect(labels).toContain("Medical Knowledge Base & Corpus");

    const edgeClientApi = result.edges.find((e) => e.id === "edge_client_api");
    expect(edgeClientApi).toBeDefined();
    expect(edgeClientApi?.label).toBe("Chat Stream / REST");
    expect(edgeClientApi?.status).toBe("broken");
  });

  it("generates tailored architecture for fullstack e-commerce platform", () => {
    const ecommerceProject: Project = {
      ...mockProjectBase,
      id: "proj-ecom",
      name: "fullstack-ecommerce-platform",
      repoUrl: "https://github.com/Ashokpanuganti/fullstack-ecommerce-platform",
      stack: ["React", "Express", "MongoDB", "Stripe", "Redis"],
    };

    const result = generateArchitecture(ecommerceProject, []);

    const nodeIds = result.nodes.map((n) => n.id);
    expect(nodeIds).toContain("node_web");
    expect(nodeIds).toContain("node_api");
    expect(nodeIds).toContain("node_auth");
    expect(nodeIds).toContain("node_db");
    expect(nodeIds).toContain("node_external");
    expect(nodeIds).toContain("node_cache");

    const dbNode = result.nodes.find((n) => n.id === "node_db");
    expect(dbNode?.tech).toBe("MongoDB (Mongoose)");

    const extNode = result.nodes.find((n) => n.id === "node_external");
    expect(extNode?.label).toBe("Stripe Payment Gateway");
  });

  it("generates tailored architecture for MERN marketplace", () => {
    const marketplaceProject: Project = {
      ...mockProjectBase,
      id: "proj-mkt",
      name: "mern-marketplace",
      repoUrl: "https://github.com/shamahoque/mern-marketplace",
      stack: ["React", "Webpack", "Express", "MongoDB", "Stripe"],
    };

    const result = generateArchitecture(marketplaceProject, []);

    const webNode = result.nodes.find((n) => n.id === "node_web");
    expect(webNode?.label).toBe("Marketplace Web Client");
    expect(webNode?.tech).toBe("React (Webpack)");

    const apiNode = result.nodes.find((n) => n.id === "node_api");
    expect(apiNode?.label).toBe("Marketplace Core Controller");

    const extNode = result.nodes.find((n) => n.id === "node_external");
    expect(extNode?.label).toBe("Stripe Connect / Escrow");
  });

  it("generates distinct architectures for different projects", () => {
    const projA: Project = {
      ...mockProjectBase,
      name: "Health-Care-Chatbot",
      stack: ["Python", "Flask", "NLTK"],
    };
    const projB: Project = {
      ...mockProjectBase,
      name: "fullstack-ecommerce-platform",
      stack: ["React", "Express", "MongoDB", "Stripe"],
    };

    const archA = generateArchitecture(projA, []);
    const archB = generateArchitecture(projB, []);

    const labelsA = archA.nodes.map((n) => n.label);
    const labelsB = archB.nodes.map((n) => n.label);

    expect(labelsA).not.toEqual(labelsB);
    expect(labelsA).toContain("Chatbot Web Interface");
    expect(labelsB).toContain("Storefront Web SPA");
  });
});
