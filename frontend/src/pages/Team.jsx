import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { Plus, Trash2, X, UserPlus } from "lucide-react";

const ROLES = [
  { value: "accountant", label: "Accountant · edit trips + invoices" },
  { value: "viewer", label: "Viewer · read-only" },
];

const EMPTY = { email: "", name: "", role: "accountant", active: true };

export default function Team() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);

  const { data: me } = useQuery({ queryKey: ["team-me"], queryFn: async () => (await api.get("/team/me")).data });
  const { data: team = [] } = useQuery({
    queryKey: ["team"],
    queryFn: async () => (await api.get("/team")).data,
    enabled: !me?.is_staff,
  });

  const add = useMutation({
    mutationFn: async () => (await api.post("/team", form)).data,
    onSuccess: () => { toast.success("Member added"); qc.invalidateQueries({ queryKey: ["team"] }); setOpen(false); setForm(EMPTY); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });
  const del = useMutation({
    mutationFn: async (id) => (await api.delete(`/team/${id}`)).data,
    onSuccess: () => { toast.success("Removed"); qc.invalidateQueries({ queryKey: ["team"] }); },
  });

  if (me?.is_staff) {
    return (
      <div data-testid="team-page">
        <h1 className="text-3xl font-black tracking-tighter mb-4">Team</h1>
        <div className="border border-zinc-200 bg-white p-6 rounded-sm text-sm">
          You are signed in as <b>{me.role}</b>. Only owners can manage team members.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="team-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Access Control</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">
            <span className="telugu">టీమ్</span>
            <span className="text-zinc-400"> · Team</span>
          </h1>
        </div>
        <button data-testid="add-team-btn" onClick={() => setOpen(true)} className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-2">
          <UserPlus size={14} /> Invite
        </button>
      </header>

      <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
        <table className="w-full text-sm" data-testid="team-table">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="text-left px-4 py-2">Email</th>
              <th className="text-left px-4 py-2">Name</th>
              <th className="text-left px-4 py-2">Role</th>
              <th className="text-left px-4 py-2">Active</th>
              <th className="text-right px-4 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {team.map((t) => (
              <tr key={t.id} className="border-t border-zinc-100" data-testid={`team-row-${t.id}`}>
                <td className="px-4 py-2 font-semibold">{t.email}</td>
                <td className="px-4 py-2">{t.name || "—"}</td>
                <td className="px-4 py-2 uppercase text-xs">{t.role}</td>
                <td className="px-4 py-2 text-xs">{t.active ? "Yes" : "No"}</td>
                <td className="px-4 py-2 text-right">
                  <button data-testid={`del-team-${t.id}`} onClick={() => { if (window.confirm(`Remove ${t.email}?`)) del.mutate(t.id); }} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-rose-200 text-rose-700 rounded-sm hover:bg-rose-50">
                    <Trash2 size={12} /> Remove
                  </button>
                </td>
              </tr>
            ))}
            {team.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-10 text-center text-zinc-400 text-sm">No team members. Invite your accountant to share access.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="text-xs text-zinc-500">
        <b>How it works:</b> Enter the Google email of the team member. When they sign in with that same Google account, they will see your company data with the role's permissions.
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-4" data-testid="team-modal">
          <div className="bg-white w-full max-w-md border border-zinc-950 rounded-sm">
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
              <h3 className="font-bold">Invite Team Member</h3>
              <button onClick={() => setOpen(false)}><X size={18} /></button>
            </div>
            <form onSubmit={(e) => { e.preventDefault(); add.mutate(); }} className="p-5 space-y-3">
              <F label="Google Email *"><input required data-testid="team-email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className={ic} placeholder="accountant@example.com" /></F>
              <F label="Name"><input data-testid="team-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={ic} /></F>
              <F label="Role"><select data-testid="team-role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} className={ic}>{ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}</select></F>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => setOpen(false)} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
                <button data-testid="save-team-btn" type="submit" disabled={add.isPending} className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">Add</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
const ic = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";
function F({ label, children }) { return (<div><label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">{label}</label><div className="mt-1">{children}</div></div>); }
