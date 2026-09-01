/**
 * Session store.
 *
 * IMPORTANT: the FastAPI backend in this repo ships **no authentication** --
 * there is no /token endpoint, no user table, and every route is open. So this
 * is a client-side session shell, not a security boundary. It exists to provide
 * the integration seam (token storage, bearer injection in lib/api.ts, and the
 * route guard in App.tsx) so swapping in Auth0 / Keycloak / an OAuth2 password
 * flow is a change to `signIn` alone.
 *
 * Do not mistake this for access control: anyone can still call the API directly.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface User {
  name: string;
  role: "operator" | "supervisor" | "admin";
}

interface AuthState {
  token: string | null;
  user: User | null;
  signIn: (name: string, role: User["role"]) => void;
  signOut: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      signIn: (name, role) =>
        set({
          // A real deployment replaces this with the issuer's access token.
          token: `dev.${btoa(JSON.stringify({ name, role, iat: Date.now() }))}`,
          user: { name, role },
        }),
      signOut: () => set({ token: null, user: null }),
    }),
    { name: "srts.session" },
  ),
);

/** Non-reactive read, for the fetch wrapper. */
export const getToken = () => useAuth.getState().token;
export const clearSession = () => useAuth.getState().signOut();
