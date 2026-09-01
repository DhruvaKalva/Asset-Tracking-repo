/**
 * Sign-in shell.
 *
 * The backend has no auth (see store/auth.ts) -- this picks a display identity
 * and role for the session and unlocks the client routes. It is labelled as such
 * on screen so nobody mistakes it for access control.
 */
import { useState } from "react";
import { useAuth, type User } from "@/store/auth";
import { inputClass, primaryButtonClass } from "@/components/primitives";

const ROLES: { value: User["role"]; label: string; blurb: string }[] = [
  { value: "supervisor", label: "Site supervisor", blurb: "Fleet view, check-in/out, acknowledge alerts" },
  { value: "operator", label: "Operator", blurb: "Scan assets, log usage" },
  { value: "admin", label: "Admin", blurb: "Everything, plus job controls" },
];

export default function Login() {
  const signIn = useAuth((s) => s.signIn);
  const [name, setName] = useState("");
  const [role, setRole] = useState<User["role"]>("supervisor");

  return (
    <div className="flex h-full items-center justify-center p-6">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          signIn(name.trim() || "Demo User", role);
        }}
        className="card w-full max-w-sm p-6"
      >
        <h1 className="text-lg font-semibold text-ink">Smart Rental Tracking</h1>
        <p className="mt-1 text-sm text-ink-2">Sign in to the fleet console.</p>

        <label className="mt-5 block">
          <span className="text-xs font-medium uppercase tracking-wide text-ink-muted">Name</span>
          <input
            className={inputClass + " mt-1 w-full"}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Demo User"
            autoFocus
          />
        </label>

        <fieldset className="mt-4">
          <legend className="text-xs font-medium uppercase tracking-wide text-ink-muted">Role</legend>
          <div className="mt-1.5 space-y-1.5">
            {ROLES.map((r) => (
              <label
                key={r.value}
                className={
                  "flex cursor-pointer items-start gap-2.5 rounded-lg border p-2.5 transition-colors " +
                  (role === r.value ? "border-[var(--accent)] bg-[var(--accent)]/8" : "border-hair hover:border-ink-muted/40")
                }
              >
                <input
                  type="radio"
                  name="role"
                  className="mt-0.5 accent-[var(--accent)]"
                  checked={role === r.value}
                  onChange={() => setRole(r.value)}
                />
                <span>
                  <span className="block text-sm font-medium text-ink">{r.label}</span>
                  <span className="block text-xs text-ink-muted">{r.blurb}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <button type="submit" className={primaryButtonClass + " mt-5 w-full justify-center"}>
          Enter console
        </button>

        <p className="mt-4 rounded-lg border border-warning/40 bg-warning/10 p-2.5 text-[11px] leading-snug text-ink-2">
          <span className="font-semibold text-warning">Demo sign-in.</span> This API ships without
          authentication, so this screen only sets a display identity — it grants no privileges and
          protects nothing. Wire an OAuth2 / Keycloak / Auth0 issuer into <code>store/auth.ts</code>
          {" "}and add dependencies to the FastAPI routes before exposing this anywhere real.
        </p>
      </form>
    </div>
  );
}
