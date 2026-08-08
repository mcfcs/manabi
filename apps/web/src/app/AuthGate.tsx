import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { LoginPage } from "../features/auth/LoginPage";
import { api, ApiError, type UserOut } from "../lib/api";
import { AppShell } from "./AppShell";

export function AuthGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const me = useQuery<UserOut | null>({
    queryKey: ["me"],
    retry: false,
    queryFn: async () => {
      try {
        return await api.get<UserOut>("/api/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
  });

  if (me.isLoading) {
    return <div className="splash">学び</div>;
  }
  if (me.isError) {
    return (
      <div className="splash">
        <p>Manabi server unreachable.</p>
        <button className="btn" onClick={() => me.refetch()}>
          Retry
        </button>
      </div>
    );
  }
  if (!me.data) {
    return (
      <LoginPage
        onAuthenticated={(user) => queryClient.setQueryData(["me"], user)}
      />
    );
  }
  return <AppShell user={me.data}>{children}</AppShell>;
}
