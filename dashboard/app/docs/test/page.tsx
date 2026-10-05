import { redirect } from "next/navigation";

// Moved in the docs rewrite; see MOVED in lib/docs.ts. Kept so old links still land.
export default function Page() {
  redirect("/docs/guides/red-team-and-evals");
}
