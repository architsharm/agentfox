import { redirect } from "next/navigation";

/** Members is a Settings tab; this address is the one people guess. */
export default function MembersRedirect() {
  redirect("/app/settings?tab=members");
}
