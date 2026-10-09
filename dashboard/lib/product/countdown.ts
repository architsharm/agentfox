/** What `<Countdown>` shows for a deadline, and how urgent it looks. */
export function formatCountdown(target: Date, now: Date): { label: string; tone: "ok" | "warn" | "bad" } {
  const ms = target.getTime() - now.getTime();
  if (ms <= 0) return { label: "expired", tone: "bad" };
  const totalMinutes = Math.floor(ms / 60000);
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  // Under a minute used to read "0m", which looks already over.
  const label =
    days > 0 ? `${days}d ${hours}h` : hours > 0 ? `${hours}h ${minutes}m` : minutes > 0 ? `${minutes}m` : "<1m";
  return { label, tone: ms < 3600_000 ? "warn" : "ok" };
}
