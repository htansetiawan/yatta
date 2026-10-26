import { FormEvent, useState } from "react";
import { api, call } from "../api/client";
import { Seal } from "../components/ui";

const waves = (
  <svg className="waves" viewBox="0 0 400 110" preserveAspectRatio="xMidYMax slice" aria-hidden="true">
    <defs>
      <pattern id="seigaiha" width="40" height="20" patternUnits="userSpaceOnUse">
        <g fill="none" stroke="#E2DACB" strokeWidth="1">
          <circle cx="20" cy="20" r="18" /><circle cx="20" cy="20" r="12" /><circle cx="20" cy="20" r="6" />
          <circle cx="0" cy="10" r="18" /><circle cx="40" cy="10" r="18" />
        </g>
      </pattern>
    </defs>
    <rect width="400" height="110" fill="url(#seigaiha)" />
  </svg>
);

export default function Landing({ onSignedIn }: { onSignedIn: () => void }) {
  const [key, setKey] = useState("");
  const [error, setError] = useState(new URLSearchParams(location.search).has("signin") ? "That key did not work." : "");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      await call(api.POST("/api/v1/session", { body: { key } }));
      history.replaceState(null, "", location.pathname);
      onSignedIn();
    } catch (err) { setError((err as Error).message); }
    setBusy(false);
  };
  return (
    <div className="landing">
      {waves}
      <div className="vertical" aria-hidden="true">あなたの顔と声で、どんな言葉も。</div>
      <form className="hero" onSubmit={submit}>
        <Seal size={84} />
        <div className="name">Yatta</div>
        <div className="jp" style={{ fontSize: 18, marginTop: -6 }}>やった</div>
        <p className="tagline">Your face. Your voice. Any words.</p>
        <div className="signin">
          <input className="input" type="password" placeholder="Access key" value={key} onChange={(e) => setKey(e.target.value)} autoFocus aria-label="Access key" />
          <button className="btn primary lg" disabled={!key || busy}>Enter</button>
        </div>
        <p className="small" style={{ color: "var(--shu-ink)", minHeight: 20 }} role="alert">{error}</p>
        <p className="small faint">A personal avatar studio. Access by key.</p>
      </form>
    </div>
  );
}
