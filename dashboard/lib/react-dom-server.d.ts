// The dashboard has no @types/react-dom. Component tests render to static HTML with
// react-dom/server (a runtime dependency of Next); this is the one function they use.
declare module "react-dom/server" {
  import type { ReactElement } from "react";
  export function renderToStaticMarkup(element: ReactElement): string;
}
