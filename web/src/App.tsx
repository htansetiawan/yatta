import { useCallback, useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { api, call, Status } from "./api/client";
import { Seal, usePoll } from "./components/ui";
import Landing from "./pages/Landing";
import Create from "./pages/Create";
import Avatars from "./pages/Avatars";
import Voices from "./pages/Voices";
import Train, { TrainDetail } from "./pages/Train";
import Library from "./pages/Library";

const NAV = [
  { to: "/create", label: "Create", kanji: "作る", icon: <path d="M4 15.5V16h.5L14 6.5 13.5 6 4 15.5zM12.8 4.7l2.5 2.5 1.2-1.2a1 1 0 000-1.4l-1.1-1.1a1 1 0 00-1.4 0l-1.2 1.2z" /> },
  { to: "/avatars", label: "Avatars", kanji: "顔", icon: <><circle cx="10" cy="7" r="3.2" /><path d="M3.5 17c.8-3.4 3.3-5 6.5-5s5.7 1.6 6.5 5" /></> },
  { to: "/voices", label: "Voices", kanji: "声", icon: <path d="M10 3v14M6.5 6.5v7M3 9v2M13.5 6.5v7M17 9v2" /> },
  { to: "/train", label: "Train", kanji: "学ぶ", icon: <path d="M10 13V3.5M6 7.5l4-4 4 4M3.5 13v2.5a1 1 0 001 1h11a1 1 0 001-1V13" /> },
  { to: "/library", label: "Library", kanji: "作品", icon: <><rect x="3" y="4" width="14" height="12" rx="2" /><path d="M8.5 7.8v4.4L12.2 10z" /></> },
];

export default function App() {
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  useEffect(() => {
    call(api.GET("/api/v1/session")).then((s) => setSignedIn(s.signed_in)).catch(() => setSignedIn(false));
    const out = () => setSignedIn(false);
    window.addEventListener("yatta:signed-out", out);
    return () => window.removeEventListener("yatta:signed-out", out);
  }, []);
  if (signedIn === null) return null;
  if (!signedIn) return <Landing onSignedIn={() => setSignedIn(true)} />;
  return (
    <div className="shell">
      <Sidebar onSignOut={() => setSignedIn(false)} />
      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/create" replace />} />
          <Route path="/create" element={<Create />} />
          <Route path="/avatars" element={<Avatars />} />
          <Route path="/voices" element={<Voices />} />
          <Route path="/train" element={<Train />} />
          <Route path="/train/:id" element={<TrainDetail />} />
          <Route path="/library" element={<Library />} />
          <Route path="*" element={<Navigate to="/create" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function Sidebar({ onSignOut }: { onSignOut: () => void }) {
  const [status, setStatus] = useState<Status | null>(null);
  const refresh = useCallback(() => { call(api.GET("/api/v1/status")).then(setStatus).catch(() => {}); }, []);
  useEffect(refresh, [refresh]);
  usePoll(refresh, 30000);
  const foreign = status?.gpu.processes.filter((p) => !p.own) ?? [];
  const own = status?.gpu.processes.filter((p) => p.own) ?? [];
  let dot = "dot", label = "Checking GPU…";
  if (status) {
    if (!status.gpu.available) { dot = "dot err"; label = "GPU unavailable"; }
    else if (foreign.length && status.gpu.foreign_busy) { dot = "dot busy"; label = `GPU busy · ${foreign[0].label.split(" · ")[0]}`; }
    else if (own.length) { dot = "dot busy"; label = "Rendering"; }
    else { dot = "dot ok"; label = foreign.length ? `GPU free · ${foreign[0].label.split(" · ")[0]} idle` : "GPU idle"; }
  }
  const bits = status ? [`${status.disk_free_gb} GB free`, ...(status.queue.active ? [`${status.queue.active} rendering`] : []), ...(status.training ? [`${status.training} training`] : [])] : [];
  const signOut = async () => { await call(api.DELETE("/api/v1/session")).catch(() => {}); onSignOut(); };
  return (
    <aside className="sidebar">
      <NavLink to="/create" className="brand">
        <Seal size={32} />
        <span className="brand-text"><div className="brand-name">Yatta</div><div className="brand-jp">やった</div></span>
      </NavLink>
      <nav className="nav" aria-label="Yatta">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? "active" : "")}>
            <svg viewBox="0 0 20 20">{n.icon}</svg>{n.label}<span className="kanji">{n.kanji}</span>
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-foot">
        <div className="sys"><span className={dot} />{label}</div>
        <div className="sys-sub">{bits.join(" · ")}</div>
        <button className="btn ghost sm" style={{ marginTop: 10, marginLeft: -10 }} onClick={signOut}>Sign out</button>
      </div>
    </aside>
  );
}
