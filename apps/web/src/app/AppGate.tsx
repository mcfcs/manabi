import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { api, type UserOut } from "../lib/api";
import { AppShell } from "./AppShell";

/** Single-user mode: no login. Fetches the default user (creating it on
 * first request) and shows a clear state if the server is unreachable. */
export function AppGate({ children }: { children: ReactNode }) {
  const me = useQuery<UserOut>({
    queryKey: ["me"],
    queryFn: () => api.get<UserOut>("/api/me"),
  });

  if (me.isLoading) {
    return <div className="splash">学び</div>;
  }
  if (me.isError || !me.data) {
    return (
      <div className="splash">
        <p>Manabi server unreachable.</p>
        <button className="btn" onClick={() => me.refetch()}>
          Retry
        </button>
      </div>
    );
  }
  return <AppShell user={me.data}>{children}</AppShell>;
}
