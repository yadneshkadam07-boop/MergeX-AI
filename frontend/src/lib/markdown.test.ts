import { describe, it, expect } from "vitest";
import type React from "react";
import { MicroMarkdown } from "./markdown";
import { renderInline } from "./markdown-inline";

describe("MicroMarkdown and renderInline pure logic", () => {
  it("parses inline code tokens into code elements", () => {
    const nodes = renderInline("Run `npm test` now");
    expect(nodes).toHaveLength(3);
    const codeNode = nodes[1] as React.ReactElement<{ children: React.ReactNode }>;
    expect(codeNode.type).toBe("code");
    expect(codeNode.props.children).toBe("npm test");
  });

  it("parses bold tokens into strong elements", () => {
    const nodes = renderInline("This is **critical** security issue");
    expect(nodes).toHaveLength(3);
    const strongNode = nodes[1] as React.ReactElement<{ children: React.ReactNode }>;
    expect(strongNode.type).toBe("strong");
  });

  it("parses links into anchor elements with rel noopener", () => {
    const nodes = renderInline("Visit [docs](https://mergex.ai/docs)");
    expect(nodes).toHaveLength(2);
    const aNode = nodes[1] as React.ReactElement<{ href: string; target: string }>;
    expect(aNode.type).toBe("a");
    expect(aNode.props.href).toBe("https://mergex.ai/docs");
    expect(aNode.props.target).toBe("_blank");
  });

  it("renders headers and paragraph blocks", () => {
    const tree = MicroMarkdown({
      content: "# Title\n\n## Subtitle\n\nParagraph with `code`",
    });
    expect(tree).toBeDefined();
    expect(tree.type).toBe("div");
  });
});
