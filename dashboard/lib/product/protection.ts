/** The fields an agent protection setup may carry, from an untrusted request body. */
export function protectionSetup(body: any) {
  return {
    protections: body?.protections && typeof body.protections === "object" ? body.protections : {},
    message: String(body?.message || ""),
    words: Array.isArray(body?.words) ? body.words.map(String) : [],
    avoid: String(body?.avoid || ""),
    allowed: String(body?.allowed || ""),
  };
}
