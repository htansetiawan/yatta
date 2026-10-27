import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, call, Quick, Training, uploadFile } from "../api/client";
import { chipColor, fmtSeconds, store, timeAgo, usePoll, useToast } from "../components/ui";
import { FEATURE_LABEL } from "../components/renders";

const TRAIN_STATE: Record<string, string> = { framing: "Framing", review: "Review framing", training: "Training", ready: "Ready", failed: "Failed" };
const FEATURES: [string, string, string, boolean][] = [
  ["esperanto", "wav2vec2 · Esperanto", "Best lip sync in our tests.", true],
  ["deepspeech", "DeepSpeech", "The original GaussianTalker choice. English-only.", false],
  ["hubert", "HuBERT large", "Close second on lip sync.", false],
  ["whisper", "Whisper small", "Weakest lip sync in our tests.", false],
];

function Steps({ at }: { at: number }) {
  return <div className="steps">{["Upload", "Frame", "Train"].map((s, i) => <span key={s} style={{ display: "flex", alignItems: "center", gap: 10 }}>{i > 0 && <i />}<span className={i + 1 <= at ? "on" : ""}>{i + 1} · {s}</span></span>)}</div>;
}

export default function Train() {
  const toast = useToast();
  const navigate = useNavigate();
  const [list, setList] = useState<Training[]>([]);
  const [name, setName] = useState("");
  const [files, setFiles] = useState<{ name: string; size: number; progress: number; id?: string; seconds?: number; error?: string }[]>([]);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { call(api.GET("/api/v1/trainings")).then(setList).catch(() => {}); }, []);
  const uploading = files.some((f) => !f.id && !f.error);
  const add = async (picked: File[]) => {
    for (const f of picked) {
      const index = files.length;
      setFiles((fs) => [...fs, { name: f.name, size: f.size, progress: 0 }]);
      try {
        const rec = await uploadFile(f, "video", (p) => setFiles((fs) => fs.map((x, i) => (i === index ? { ...x, progress: p } : x))));
        setFiles((fs) => fs.map((x, i) => (i === index ? { ...x, id: rec.id, seconds: rec.seconds ?? 0 } : x)));
      } catch (e) { setFiles((fs) => fs.map((x, i) => (i === index ? { ...x, error: (e as Error).message } : x))); }
    }
  };
  const start = async () => {
    setBusy(true);
    try {
      const a = await call(api.POST("/api/v1/trainings", { body: { name, uploads: files.filter((f) => f.id).map((f) => f.id!), consent } }));
      navigate(`/train/${a.id}`);
    } catch (e) { toast((e as Error).message, true); setBusy(false); }
  };
  return (
    <>
      <div className="page-head"><div><div className="eyebrow">学ぶ</div><h1>New avatar</h1><p className="muted">A Quick avatar is ready in a minute. A trained avatar takes hours but also works on the Fast engine.</p></div></div>
      <QuickCard />
      <h2 style={{ margin: "34px 0 12px" }}>Train an avatar</h2>
      <Steps at={1} />
      <div className="two">
        <div className="card panel">
          <label className="label">Avatar name<input className="input" placeholder="e.g. Henry, studio light" value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label className="dropzone" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); add([...e.dataTransfer.files]); }}>
            <input type="file" accept="video/*" multiple hidden onChange={(e) => add([...(e.target.files ?? [])])} />
            <strong>Drop video files</strong> or click to browse<br /><span className="small faint">MOV or MP4 · 3–6 minutes · several clips are joined</span>
          </label>
          {files.length > 0 && <div className="file-list">{files.map((f, i) => (
            <div key={i} className="file-item"><div className="grow"><div style={{ fontWeight: 500 }}>{f.name}</div>
              {f.error ? <div className="small" style={{ color: "var(--shu-ink)" }}>{f.error}</div> : f.id ? <div className="small muted">{fmtSeconds(f.seconds)} · uploaded</div>
                : <div className="progress"><span style={{ width: `${Math.round(f.progress * 100)}%` }} /></div>}</div>
              <span className="small muted mono">{(f.size / 1e9).toFixed(2)} GB</span></div>
          ))}</div>}
          <label className="check"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />This is me, or this person agreed to an avatar.</label>
          <div style={{ display: "flex", justifyContent: "flex-end" }}><button className="btn primary" disabled={!files.some((f) => f.id) || !consent || uploading || busy} onClick={start}>Continue</button></div>
        </div>
        <aside className="card panel">
          <h2>Recording tips</h2>
          <ul className="tips">
            <li>3–6 minutes of natural talking, face to camera.</li>
            <li>Phone on a stand at eye level; keep the frame steady.</li>
            <li>One room and even light.</li>
            <li>No sunglasses, captions or hands in front of the face.</li>
            <li>Clothes and hair are baked into the avatar.</li>
          </ul>
        </aside>
      </div>
      {list.length > 0 && <>
        <h2 style={{ margin: "36px 0 12px" }}>Your trainings</h2>
        <div className="card">{list.map((a) => (
          <Link key={a.id} className="job-row" to={`/train/${a.id}`}>
            <span className="chip" style={{ background: chipColor(a.id) }}>{a.name[0] ?? "A"}</span>
            <div className="grow"><div className="title">{a.name}</div><div className="small muted">{timeAgo(a.created)} · {summary(a)}</div></div>
            <span className={`badge ${a.state === "ready" ? "ok" : a.state === "failed" ? "shu" : a.state === "review" ? "ink" : "warn"}`}>{TRAIN_STATE[a.state] ?? a.state}</span>
          </Link>
        ))}</div>
      </>}
    </>
  );
}

function summary(a: Training) {
  if (a.state === "training") { const last = a.events?.[a.events.length - 1]?.[1]; return last ? last.replace(/^waiting for GPU: /, "Waiting for GPU · ") : "Starting"; }
  if (a.state === "ready") return `${a.ready_features.map((f) => FEATURE_LABEL[f] ?? f).join(", ")} ready`;
  return a.failure ?? "";
}

function QuickCard() {
  const toast = useToast();
  const [items, setItems] = useState<Quick[]>([]);
  const [name, setName] = useState("");
  const [upload, setUpload] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [consent, setConsent] = useState(false);
  const refresh = useCallback(() => call(api.GET("/api/v1/quick")).then(setItems).catch(() => {}), []);
  useEffect(() => { refresh(); }, [refresh]);
  usePoll(refresh, 4000, items.some((q) => q.state === "preparing"));
  const pick = async (f?: File) => {
    if (!f) return;
    setStatus("Uploading… 0%");
    try {
      const rec = await uploadFile(f, "video", (p) => setStatus(`Uploading… ${Math.round(p * 100)}%`));
      setUpload(rec.id); setStatus(`${fmtSeconds(rec.seconds)} uploaded`);
      if (!name) setName(f.name.replace(/\.[^.]+$/, ""));
    } catch (e) { setStatus((e as Error).message); }
  };
  const create = async () => {
    try {
      await call(api.POST("/api/v1/quick", { body: { name, upload: upload!, consent } }));
      setUpload(null); setName(""); setStatus(""); setConsent(false);
      toast("Creating the Quick avatar — about a minute"); refresh();
    } catch (e) { toast((e as Error).message, true); }
  };
  return (
    <div className="card panel">
      <div><h2>Quick avatar <span className="badge shu" style={{ marginLeft: 6 }}>No training</span></h2>
        <p className="small muted" style={{ marginTop: 4 }}>No training. Upload 15–60 seconds of someone talking to the camera; Yatta regenerates the mouth on this clip.</p></div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
        <input className="input" style={{ flex: "1 1 220px" }} placeholder="Name, e.g. Henry · garden" value={name} onChange={(e) => setName(e.target.value)} />
        <label className="btn sm">Choose video<input type="file" accept="video/*" hidden onChange={(e) => pick(e.target.files?.[0])} /></label>
        <span className="small muted">{status}</span>
      </div>
      <label className="check"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />This is me, or this person agreed to an avatar.</label>
      <div style={{ display: "flex", justifyContent: "flex-end" }}><button className="btn primary" disabled={!upload || !consent} onClick={create}>Create Quick avatar</button></div>
      {items.length > 0 && <div className="file-list">{items.map((q) => (
        <div key={q.id} className="file-item"><div className="grow"><div style={{ fontWeight: 500 }}>{q.name}</div>
          <div className="small muted">{q.state === "ready" ? `${fmtSeconds(q.seconds)} clip · ready in Create` : q.state === "failed" ? q.detail : "Cropping…"}</div></div>
          <span className={`badge ${q.state === "ready" ? "ok" : q.state === "failed" ? "shu" : "warn"}`}>{q.state}</span></div>
      ))}</div>}
    </div>
  );
}

type Crop = { x: number; y: number; size: number; width: number; height: number; frames: string[]; seconds: number; upload: string };

export function TrainDetail() {
  const { id = "" } = useParams();
  const toast = useToast();
  const navigate = useNavigate();
  const [a, setA] = useState<Training | null>(null);
  const refresh = useCallback(() => call(api.GET("/api/v1/trainings/{avatar_id}", { params: { path: { avatar_id: id } } })).then(setA).catch((e) => toast(e.message, true)), [id, toast]);
  useEffect(() => { refresh(); }, [refresh]);
  usePoll(refresh, a?.state === "framing" ? 4000 : 20000, a?.state === "framing" || a?.state === "training");
  if (!a) return null;
  const head = <div className="page-head"><div><div className="eyebrow">学ぶ</div><h1>{a.name}</h1><p className="muted">Started {timeAgo(a.created)}</p></div><Link className="btn ghost" to="/train">All trainings</Link></div>;
  if (a.state === "framing") return <>{head}<Steps at={2} /><div className="card panel" style={{ alignItems: "center", padding: 56 }}><span className="spinner" /><p className="muted">Finding the face in each video…</p></div></>;
  if (a.state === "review") return <>{head}<Steps at={2} /><Review a={a} onDone={refresh} onDiscard={() => navigate("/train")} /></>;
  const last = a.events?.[a.events.length - 1]?.[1] ?? "";
  const crops = (a.crops ?? []) as unknown as Crop[];
  return (
    <>{head}<Steps at={3} />
      <div className="two">
        <div className="card panel">
          {a.state === "ready" && <div className="notice ok">Ready: {a.ready_features.map((f) => FEATURE_LABEL[f] ?? f).join(", ")}.</div>}
          {a.state === "failed" && <div className="notice err">{a.failure ?? "Training stopped."}</div>}
          {last.startsWith("waiting for GPU") && <div className="notice warn">Another project is using the GPU ({last.replace("waiting for GPU: ", "")}). Training resumes when it finishes.</div>}
          {a.features.map((f) => {
            const p = (a.progress as Record<string, { stage: string; iteration: number; total: number; remaining: string; overall: number } | null>)[f];
            const done = a.ready_features.includes(f);
            return <div key={f}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}><span style={{ fontWeight: 500 }}>{FEATURE_LABEL[f] ?? f}</span>
                <span className="small muted mono">{done ? "Ready" : p ? `${p.stage} ${p.iteration.toLocaleString()}/${p.total.toLocaleString()} · ${p.remaining} left` : "Not started"}</span></div>
              <div className="progress"><span style={{ width: `${done ? 100 : p?.overall ?? 0}%` }} /></div></div>;
          })}
          <div><div className="section-label"><span>Activity</span></div><div className="timeline">{[...(a.events ?? [])].slice(-14).reverse().map(([t, m], i) => (
            <div key={i} className={`tl-item${i === 0 ? " last" : ""}`}><span className="mark" /><span>{m}</span><span className="small faint mono">{new Date(t).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span></div>
          ))}</div></div>
          <div style={{ display: "flex", gap: 8 }}>
            {a.state === "failed" && <button className="btn primary" onClick={async () => { try { setA(await call(api.POST("/api/v1/trainings/{avatar_id}/retry", { params: { path: { avatar_id: id } } }))); } catch (e) { toast((e as Error).message, true); } }}>Retry</button>}
            {a.state === "ready" && <button className="btn primary" onClick={() => { store.set("create", { ...store.get("create", {}), avatar: id, feature: a.ready_features[0] }); navigate("/create"); }}>Use in Create</button>}
          </div>
        </div>
        <aside className="card panel"><h2>Framing</h2>
          {crops.map((c, i) => <div key={i} className="crop-frame"><img alt="" src={`/media/training/${id}/${c.frames[1]}`} /><div className="crop-box" style={boxStyle(c)} /></div>)}
        </aside>
      </div>
    </>
  );
}

const boxStyle = (c: { x: number; y: number; size: number; width: number; height: number }) => ({
  left: `${(c.x / c.width) * 100}%`, top: `${(c.y / c.height) * 100}%`, width: `${(c.size / c.width) * 100}%`, height: `${(c.size / c.height) * 100}%`,
});

function Review({ a, onDone, onDiscard }: { a: Training; onDone: () => void; onDiscard: () => void }) {
  const toast = useToast();
  const proposals = (a.crops ?? []) as unknown as Crop[];
  const [crops, setCrops] = useState(proposals.map((c) => ({ x: c.x, y: c.y, size: c.size })));
  const [features, setFeatures] = useState<string[]>(["esperanto"]);
  const drag = useRef<{ i: number; sx: number; sy: number; cx: number; cy: number; scale: number } | null>(null);
  const set = (i: number, patch: Partial<{ x: number; y: number; size: number }>) => setCrops((cs) => cs.map((c, k) => (k === i ? { ...c, ...patch } : c)));
  const start = async () => {
    try { await call(api.POST("/api/v1/trainings/{avatar_id}/approve", { params: { path: { avatar_id: a.id } }, body: { crops, features } })); onDone(); }
    catch (e) { toast((e as Error).message, true); }
  };
  const discard = async () => {
    if (!confirm("Discard this avatar? The framing and this training entry are removed.")) return;
    await call(api.DELETE("/api/v1/trainings/{avatar_id}", { params: { path: { avatar_id: a.id } } })); onDiscard();
  };
  return (
    <div className="two">
      <div className="card panel">
        <div><h2>Check the framing</h2><p className="small muted" style={{ marginTop: 4 }}>The square becomes the training frame. Keep the whole head, some hair and the top of the shoulders inside it. Drag to move; the slider resizes.</p></div>
        {proposals.map((p, i) => (
          <div key={i}>
            <div className="section-label"><span>Video {i + 1} · {fmtSeconds(p.seconds)}</span><button className="btn ghost sm" onClick={() => set(i, { x: p.x, y: p.y, size: p.size })}>Reset</button></div>
            <div className="cropper">{p.frames.map((f) => (
              <div key={f} className="crop-frame">
                <img alt="" src={`/media/training/${a.id}/${f}`} />
                <div className="crop-box" style={boxStyle({ ...p, ...crops[i] })}
                  onPointerDown={(e) => {
                    e.preventDefault(); (e.target as HTMLElement).setPointerCapture(e.pointerId);
                    const rect = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect();
                    drag.current = { i, sx: e.clientX, sy: e.clientY, cx: crops[i].x, cy: crops[i].y, scale: p.width / rect.width };
                  }}
                  onPointerMove={(e) => {
                    const d = drag.current; if (!d || d.i !== i) return;
                    set(i, { x: Math.round(Math.max(0, Math.min(p.width - crops[i].size, d.cx + (e.clientX - d.sx) * d.scale))),
                             y: Math.round(Math.max(0, Math.min(p.height - crops[i].size, d.cy + (e.clientY - d.sy) * d.scale))) });
                  }}
                  onPointerUp={() => (drag.current = null)} />
              </div>
            ))}</div>
            <label className="label" style={{ marginTop: 10 }}>Size<input type="range" min={256} max={Math.min(p.width, p.height)} value={crops[i].size} onChange={(e) => {
              const size = +e.target.value, c = crops[i], cx = c.x + c.size / 2, cy = c.y + c.size / 2;
              set(i, { size, x: Math.round(Math.max(0, Math.min(p.width - size, cx - size / 2))), y: Math.round(Math.max(0, Math.min(p.height - size, cy - size / 2))) });
            }} /></label>
          </div>
        ))}
      </div>
      <aside className="card panel">
        <h2>Speech models</h2>
        <p className="small muted">Each is a separate training run of about 4–5 hours.</p>
        {FEATURES.map(([f, label, note, rec]) => (
          <label key={f} className="feature-opt"><input type="checkbox" checked={features.includes(f)} onChange={(e) => setFeatures((fs) => (e.target.checked ? [...fs, f] : fs.filter((x) => x !== f)))} />
            <span><span style={{ fontWeight: 500 }}>{label}</span> {rec && <span className="badge ink">Recommended</span>}<br /><span className="small muted">{note}</span></span></label>
        ))}
        <p className="small muted mono">{features.length ? `≈ 2 h preparation + ${features.length} × 4.5 h training` : "Choose at least one model"}</p>
        <button className="btn primary" disabled={!features.length} onClick={start}>Start training</button>
        <button className="btn ghost danger" onClick={discard}>Discard</button>
      </aside>
    </div>
  );
}
