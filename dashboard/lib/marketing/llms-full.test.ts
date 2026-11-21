import { describe, expect, it } from "vitest";

import { htmlToText } from "./llms-full";

describe("htmlToText", () => {
  it("keeps the main element's words and drops chrome, scripts and tags", () => {
    const html =
      '<html><body><nav>Home Docs</nav><main><h1>Quickstart</h1><script>x()</script><p>Run <code>agentfox init</code> &amp; wait.<button>Copy</button></p><p>It&#x27;s &#8212; done</p><svg><path d="M0"/></svg></main><footer>f</footer></body></html>';
    expect(htmlToText(html)).toBe("Quickstart\nRun agentfox init & wait.\nIt's — done");
  });
  it("falls back to the whole document when there is no main", () => {
    expect(htmlToText("<p>a</p><p>b</p>")).toBe("a\nb");
  });
});
