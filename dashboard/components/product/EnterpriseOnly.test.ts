import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { EnterpriseOnly } from "./EnterpriseOnly";

describe("EnterpriseOnly", () => {
  it("says how to install Enterprise, without markdown backticks in the page", () => {
    const html = renderToStaticMarkup(createElement(EnterpriseOnly, { feature: "evidence" }));
    expect(html).not.toContain("`");
    expect(html).toContain("<code>pip install agentfox ./ee</code>");
    expect(html).toContain("not on PyPI");
  });
});
