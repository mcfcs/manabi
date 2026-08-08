import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, ApiError, type UserOut } from "../../lib/api";
import "./auth.css";

export function LoginPage({
  onAuthenticated,
}: {
  onAuthenticated: (user: UserOut) => void;
}) {
  const setup = useQuery({
    queryKey: ["setup-required"],
    queryFn: () =>
      api.get<{ setup_required: boolean }>("/api/auth/setup-required"),
  });
  const isSetup = setup.data?.setup_required === true;

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = await api.post<UserOut>(
        isSetup ? "/api/auth/register" : "/api/auth/login",
        { email, password },
      );
      onAuthenticated(user);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-mark" aria-hidden>
          学び
        </div>
        <h1>Manabi</h1>
        <p className="auth-sub">
          {isSetup
            ? "Welcome. Create your account to begin."
            : "Your study workspace."}
        </p>

        <label className="field-label" htmlFor="email">
          Email
        </label>
        <input
          id="email"
          className="input"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />

        <label className="field-label" htmlFor="password">
          Password
        </label>
        <input
          id="password"
          className="input"
          type="password"
          autoComplete={isSetup ? "new-password" : "current-password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={isSetup ? 10 : undefined}
        />

        {error && <p className="error-text">{error}</p>}

        <button className="btn btn-primary auth-submit" disabled={busy}>
          {busy ? "…" : isSetup ? "Create account" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
