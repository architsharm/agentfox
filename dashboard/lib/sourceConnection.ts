/**
 * The connection body for `POST /api/sources/connections`, built from a source form.
 * Shared by the row-level "Connect" form (sources/connections) and the single-flow
 * "Add a source" form (sources/add) so the two cannot drift on field names or
 * defaults. `config` is nested and its fields depend on `kind`, which is why this is
 * not a verbatim form forward.
 */
export function connectionBody(
  form: FormData,
  key: string,
  kind: string,
): Record<string, unknown> {
  const str = (name: string) => String(form.get(name) || "").trim();
  const config: Record<string, unknown> =
    kind === "database"
      ? {
          dialect: str("dialect") || "postgresql",
          host: str("host") || undefined,
          port: str("port") ? Number(str("port")) : undefined,
          database: str("database") || undefined,
          username: str("username") || undefined,
          check_table: str("check_table") || undefined,
        }
      : {
          base_url: str("base_url"),
          auth_header: str("auth_header") || "Authorization",
          auth_prefix: str("auth_prefix") || "Bearer ",
        };
  const body: Record<string, unknown> = { key, kind, config };
  const credential = str("credential");
  if (credential) body.credential = credential;
  return body;
}
