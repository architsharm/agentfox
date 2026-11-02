/**
 * A gateway error as one readable line. FastAPI's validation errors are a list of
 * `{loc, msg}` objects, which landed in the notice as "[object Object],[object Object]".
 */
export function detailText(detail: unknown): string {
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((d: any) => {
        const field = Array.isArray(d?.loc) ? d.loc.filter((x: unknown) => x !== "body").join(".") : "";
        const msg = d?.msg ?? (typeof d === "string" ? d : JSON.stringify(d));
        return field ? `${field}: ${msg}` : String(msg);
      })
      .join("; ");
  if (typeof detail === "object" && detail !== null && "message" in detail) return String((detail as any).message);
  return JSON.stringify(detail);
}
