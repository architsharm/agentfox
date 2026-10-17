/** The files an import refers to (a policy manifest's .rego bundle): path -> text, strings only. */
export function importFiles(files: unknown): Record<string, string> {
  if (!files || typeof files !== "object" || Array.isArray(files)) return {};
  const out: Record<string, string> = {};
  for (const [path, text] of Object.entries(files as Record<string, unknown>)) {
    if (typeof text === "string") out[String(path)] = text;
  }
  return out;
}
