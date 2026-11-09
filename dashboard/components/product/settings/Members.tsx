import { safeApi } from "@/lib/product/api";
import { Card, Empty, Pill } from "@/components/kit";
import { MemberAdd, MemberRow } from "@/components/product/settings/MemberControls";

/** Settings → Members: who is in this workspace, and adding a teammate (owners and admins). */
export async function MembersTab() {
  const [list, me] = await Promise.all([
    safeApi<any>("/api/members", { members: [], roles: [] }),
    safeApi<any>("/api/me", null),
  ]);
  const manage = me?.role === "owner" || me?.role === "admin";
  const members: any[] = list.members || [];
  const roles: string[] = list.roles || [];
  return (
    <>
      {manage && (
        <Card
          title="Add a teammate"
          hint="They get a sign-in key, shown once: they paste it on the sign-in page. Their role decides what they can change."
        >
          <MemberAdd roles={roles} />
        </Card>
      )}
      <Card title={`Members · ${members.length}`} flush>
        {members.length ? (
          <table className="k-table">
            <thead>
              <tr>
                <th>Member</th>
                <th className="tight">Role</th>
                <th className="tight">Status</th>
                <th className="tight" />
              </tr>
            </thead>
            <tbody>
              {members.map((m) =>
                manage && m.id !== me?.id ? (
                  <MemberRow key={m.id} member={m} roles={roles} />
                ) : (
                  <tr key={m.id}>
                    <td>
                      <span className="k-name">{m.email}</span>
                      {m.id === me?.id && <span className="sub">You</span>}
                    </td>
                    <td className="tight">{m.role}</td>
                    <td className="tight">{m.active ? <Pill tone="ok">Active</Pill> : <Pill tone="outline">Deactivated</Pill>}</td>
                    <td className="tight" />
                  </tr>
                ),
              )}
            </tbody>
          </table>
        ) : (
          <Empty>No members to show.</Empty>
        )}
      </Card>
    </>
  );
}
