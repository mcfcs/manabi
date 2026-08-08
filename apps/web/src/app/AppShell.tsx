import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { BookOpen, Home, Settings } from "lucide-react";
import type { ReactNode } from "react";

import { api, type HealthOut, type UserOut } from "../lib/api";
import "./shell.css";

function AiStatus() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => api.get<HealthOut>("/api/health"),
    refetchInterval: 30_000,
  });
  const online = health.data?.ai_node.online === true;
  return (
    <div className="ai-status" title={online ? "AI node online" : "AI node offline"}>
      <span className={online ? "status-dot online" : "status-dot"} />
      <span className="ai-status-label">AI</span>
    </div>
  );
}

export function AppShell({
  user,
  children,
}: {
  user: UserOut;
  children: ReactNode;
}) {
  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <Link to="/" className="rail-mark">
          <span className="rail-kanji" aria-hidden>
            学び
          </span>
          <span className="rail-name">MANABI</span>
        </Link>

        <div className="rail-links">
          <Link to="/" className="rail-link" activeProps={{ className: "rail-link active" }}>
            <BookOpen size={18} strokeWidth={1.5} />
            <span>Courses</span>
          </Link>
        </div>

        <div className="rail-foot">
          <AiStatus />
          <div className="rail-user mono" title={user.email}>
            {user.email}
          </div>
          <button className="rail-link rail-settings" type="button">
            <Settings size={18} strokeWidth={1.5} />
            <span>Settings</span>
          </button>
        </div>
      </nav>

      <main className="content">{children}</main>

      <nav className="bottom-bar" aria-label="Main">
        <Link to="/" className="bottom-link" activeProps={{ className: "bottom-link active" }}>
          <Home size={20} strokeWidth={1.5} />
          <span>Home</span>
        </Link>
        <div className="bottom-link" aria-hidden>
          <AiStatus />
        </div>
      </nav>
    </div>
  );
}
