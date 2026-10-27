import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, Avatar, Background, call, Render, RenderCreate, Status, uploadFile, VoiceCatalogue } from "../api/client";
import { chipColor, fmtSeconds, icons, store, usePoll, useToast } from "../components/ui";
import { isActive, jobEngine, JobRow, PublishModal } from "../components/renders";
import { CloneDialog } from "./Voices";

type Mode = "text" | "upload" | "record";
type Provider = "clone" | "elevenlabs" | "mms";
type Engine = "latentsync" | "gaussiantalker";
type Bg = { type: "original" } | { type: "color"; value: string } | { type: "image"; upload: string };
interface Draft {
  mode: Mode; text: string; provider: Provider; voice: string; engine: Engine; avatar?: string; feature?: string; background: Bg;
}
const COLORS = ["#ffffff", "#f1ede6", "#dfe4ea", "#e8e0d2", "#1c1c1c"];

export default function Create() {
  const toast = useToast();
  const [draft, setDraft] = useState<Draft>(() => ({
    mode: "text", text: "", provider: "elevenlabs", voice: "nPczCjzI2devNBz1zQrb", engine: "latentsync", background: { type: "original" },
    ...store.get<Partial<Draft>>("create", {}),
  }));
  const [avatars, setAvatars] = useState<Avatar[]>([]);
  const [voices, setVoices] = useState<VoiceCatalogue | null>(null);
  const [backgrounds, setBackgrounds] = useState<Background[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [renders, setRenders] = useState<Render[]>([]);
  const [focus, setFocus] = useState<string | null>(null);
  const [upload, setUpload] = useState<{ id: string; name: string; seconds: number } | null>(null);
  const [sharing, setSharing] = useState<Render | null>(null);
  const [cloning, setCloning] = useState(false);
  const [busy, setBusy] = useState(false);

  const update = (patch: Partial<Draft>) => setDraft((d) => {
    const next = { ...d, ...patch };
    store.set("create", next);
    return next;
  });
  const refreshRenders = useCallback(() => call(api.GET("/api/v1/renders")).then(setRenders).catch(() => {}), []);
  const refreshVoices = useCallback(() => call(api.GET("/api/v1/voices")).then(setVoices).catch(() => {}), []);
  useEffect(() => {
    call(api.GET("/api/v1/avatars")).then(setAvatars).catch((e) => toast(e.message, true));
    call(api.GET("/api/v1/backgrounds")).then(setBackgrounds).catch(() => {});
    call(api.GET("/api/v1/status")).then(setStatus).catch(() => {});
    refreshVoices();
    refreshRenders();
  }, [refreshRenders, refreshVoices, toast]);
  usePoll(refreshRenders, 3000, renders.some(isActive));
  const removeRender = async (j: Render) => {
    try { await call(api.DELETE("/api/v1/renders/{job_id}", { params: { path: { job_id: j.id } } })); refreshRenders(); }
    catch (e) { toast((e as Error).message, true); }
  };
  usePoll(refreshVoices, 5000, !!voices?.clone.some((v) => v.state === "preparing"));

  const realistic = draft.engine === "latentsync" && status?.latentsync !== false;
  const pickable = useMemo(() => avatars.filter((a) => realistic || a.engines.includes("gaussiantalker")), [avatars, realistic]);
  const avatar = pickable.find((a) => a.id === draft.avatar) ?? pickable[0];
  const feature = avatar?.variants.find((v) => v.feature === draft.feature)?.feature ?? avatar?.default_feature;
  const voiceList = voices ? voices[draft.provider] : [];
  const focused = renders.find((j) => j.id === focus) ?? renders.find((j) => j.state === "done");

  const generate = async () => {
    if (!avatar) return;
    const body: RenderCreate = {
      avatar: avatar.id, feature: feature ?? avatar.default_feature, engine: realistic ? "latentsync" : "gaussiantalker",
      background: draft.background, voice: { provider: "elevenlabs" }, text: "",
    };
    if (draft.mode === "text") {
      if (!draft.text.trim()) return toast("Write something for the avatar to say", true);
      if (!draft.voice) return toast("Pick a voice first", true);
      Object.assign(body, { text: draft.text.trim(), voice: { provider: draft.provider, id: draft.voice } });
    } else {
      if (!upload) return toast("Upload or record audio first", true);
      Object.assign(body, { voice: { provider: "upload" }, audio_upload: upload.id, title: draft.mode === "record" ? "Recorded voice" : upload.name });
    }
    setBusy(true);
    try {
      const job = await call(api.POST("/api/v1/renders", { body }));
      setFocus(job.id);
      toast("Queued — rendering starts in a moment");
      refreshRenders();
    } catch (e) { toast((e as Error).message, true); }
    setBusy(false);
  };

  const words = draft.text.trim() ? draft.text.trim().split(/\s+/).length : 0;
  return (
    <>
      <div className="page-head">
        <div><div className="eyebrow">作る</div><h1>Create</h1><p className="muted">Write a script, pick a voice and a face, and Yatta renders the video.</p></div>
      </div>
      <div className="create">
        <div>
          <div className="card composer">
            <div className="tabs" role="tablist">
              {(["text", "upload", "record"] as Mode[]).map((m) => (
                <button key={m} className={`tab${draft.mode === m ? " active" : ""}`} onClick={() => update({ mode: m })}>
                  {{ text: "Text to speech", upload: "Upload audio", record: "Record" }[m]}
                </button>
              ))}
            </div>
            {draft.mode === "text" && <textarea value={draft.text} maxLength={5000} placeholder="What should your avatar say?" aria-label="Script" onChange={(e) => update({ text: e.target.value })} />}
            {draft.mode === "upload" && <UploadPane upload={upload} setUpload={setUpload} />}
            {draft.mode === "record" && <RecordPane upload={upload} setUpload={setUpload} />}
            <div className="composer-foot">
              <span className="small muted mono">
                {draft.mode === "text" ? `${draft.text.length.toLocaleString()} / 5,000 · ~${fmtSeconds(words / 2.6) || "0s"}` : upload ? `${upload.name} · ${fmtSeconds(upload.seconds)}` : "No audio yet"}
              </span>
              <button className="btn shu lg" disabled={busy} onClick={generate}>{icons.spark}Generate</button>
            </div>
          </div>

          {focused?.state === "done" && (
            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", alignItems: "flex-start", margin: "26px 0 22px" }}>
              <div className="player" style={{ flex: "1 1 320px" }}><video key={focused.id} src={focused.video_url ?? ""} poster={focused.poster_url ?? ""} controls playsInline /></div>
              <div style={{ flex: "0 1 230px", display: "flex", flexDirection: "column", gap: 10 }}>
                <h2>{focused.title}</h2>
                <p className="small muted">{focused.avatar_name} · {jobEngine(focused)} · {fmtSeconds(focused.duration)}</p>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <a className="btn sm" href={focused.video_url ?? ""} download>{icons.download}Download</a>
                  <button className="btn sm" onClick={() => setSharing(focused)}>{icons.share}Share</button>
                </div>
              </div>
            </div>
          )}
          {renders.length > 0 && <>
            <div className="section-label" style={{ marginTop: 26 }}><span>Recent<span className="kanji">最近</span></span><Link className="faint small" to="/library">See all</Link></div>
            <div className="card">{renders.slice(0, 6).map((j) => (
              <JobRow key={j.id} job={j} onPlay={() => setFocus(j.id)} onDelete={() => removeRender(j)} onCheckGpu={async () => { await call(api.POST("/api/v1/gpu/check")); toast("Checking the GPU now"); }} />
            ))}</div>
          </>}
        </div>

        <aside className="settings">
          <section>
            <div className="section-label"><span>Engine<span className="kanji">方式</span></span></div>
            <div className="picker">
              <button className={`option${realistic ? " selected" : ""}`} onClick={() => update({ engine: "latentsync" })}>
                <span className="grow"><span className="title">Realistic <span className="badge shu">Recommended</span></span>
                  <span className="sub">Your real footage, new mouth · ~1.5 min per 10 s</span></span>
              </button>
              <button className={`option${realistic ? "" : " selected"}`} onClick={() => update({ engine: "gaussiantalker" })}>
                <span className="grow"><span className="title">Fast</span><span className="sub">3D avatar · ~20 s · custom backgrounds</span></span>
              </button>
            </div>
          </section>

          <section>
            <div className="section-label"><span>Face<span className="kanji">顔</span></span><Link className="faint small" to="/avatars">Browse</Link></div>
            <div className="picker">{pickable.map((a) => (
              <button key={a.id} className={`option${a.id === avatar?.id ? " selected" : ""}`} onClick={() => update({ avatar: a.id, feature: a.default_feature })}>
                <img className="thumb" alt="" src={a.variants.find((v) => v.poster_url)?.poster_url ?? ""} />
                <span className="grow"><span className="title">{a.name}{a.edition ? ` ${a.edition}` : ""}{a.source !== "experiment" && <span className="badge">{a.source}</span>}</span>
                  <span className="sub">{a.summary}</span></span>
              </button>
            ))}</div>
          </section>

          {avatar && !realistic && avatar.variants.length > 1 && (
            <section>
              <div className="section-label"><span>Speech model<span className="kanji">音声</span></span><span className="faint small">lip-sync error ↓</span></div>
              <div className="picker">{avatar.variants.map((v) => (
                <button key={v.feature} className={`option${v.feature === feature ? " selected" : ""}`} onClick={() => update({ feature: v.feature })}>
                  <span className="grow"><span className="title">{v.label}{v.feature === avatar.default_feature && <span className="badge ink">Best</span>}</span><span className="sub">{v.note}</span></span>
                  <span className="small muted mono">{(v.metrics as { lse_d?: number }).lse_d?.toFixed(2) ?? ""}</span>
                </button>
              ))}</div>
            </section>
          )}

          <section>
            <div className="section-label"><span>Voice<span className="kanji">声</span></span></div>
            {draft.mode === "text" ? <>
              <div className="seg">{(["clone", "elevenlabs", "mms"] as Provider[]).map((p) => (
                <button key={p} className={draft.provider === p ? "active" : ""} onClick={() => {
                  const ready = (voices?.[p] ?? []).filter((v) => !v.state || v.state === "ready");
                  update({ provider: p, voice: ready[0]?.id ?? "" });
                }}>{{ clone: "My voices", elevenlabs: "ElevenLabs", mms: "Free" }[p]}</button>
              ))}</div>
              {draft.provider === "clone" && <button className="btn sm" style={{ width: "100%", marginBottom: 8 }} onClick={() => setCloning(true)}>＋ Clone a voice</button>}
              {draft.provider === "elevenlabs" && status && !status.elevenlabs && <div className="notice warn">No ElevenLabs key on the server.</div>}
              <div className="voice-list">{voiceList.map((v) => {
                const ready = !v.state || v.state === "ready";
                return (
                  <div key={v.id} className={`option${v.id === draft.voice ? " selected" : ""}${ready ? "" : " disabled"}`} role="button" tabIndex={0}
                    onClick={() => ready && update({ voice: v.id })}>
                    <span className="chip" style={{ background: chipColor(v.id) }}>{v.name[0]}</span>
                    <span className="grow"><span className="title">{v.name}{v.state === "preparing" && <span className="badge warn">Preparing</span>}{v.state === "failed" && <span className="badge shu">Failed</span>}</span>
                      <span className="sub">{v.state === "failed" ? v.detail : [v.gender, v.accent, v.style].filter(Boolean).join(" · ")}</span></span>
                    {ready && <SampleButton provider={draft.provider} voiceId={v.id} sampleUrl={v.sample_url} />}
                  </div>
                );
              })}</div>
            </> : <div className="notice">Your uploaded or recorded audio is the voice.</div>}
          </section>

          <section>
            <div className="section-label"><span>Background<span className="kanji">背景</span></span></div>
            {realistic ? <div className="notice">Realistic videos keep the room from the recording.</div> : <>
              <div className="swatches">
                <button className={`swatch original${draft.background.type === "original" ? " selected" : ""}`} title="Original backdrop" onClick={() => update({ background: { type: "original" } })} />
                {COLORS.map((hex) => (
                  <button key={hex} className={`swatch${draft.background.type === "color" && draft.background.value === hex ? " selected" : ""}`} style={{ background: hex }} title={hex}
                    onClick={() => update({ background: { type: "color", value: hex } })} />
                ))}
                {backgrounds.map((b) => (
                  <button key={b.id} className={`swatch${draft.background.type === "image" && draft.background.upload === b.id ? " selected" : ""}`} style={{ backgroundImage: `url('${b.url}')` }} title={b.name}
                    onClick={() => update({ background: { type: "image", upload: b.id } })} />
                ))}
                <label className="swatch add" title="Upload a background image">+<input type="file" accept="image/*" hidden onChange={async (e) => {
                  const f = e.target.files?.[0]; if (!f) return;
                  try {
                    const rec = await uploadFile(f, "background");
                    setBackgrounds(await call(api.GET("/api/v1/backgrounds")));
                    update({ background: { type: "image", upload: rec.id } });
                  } catch (err) { toast((err as Error).message, true); }
                }} /></label>
              </div>
              <p className="small faint" style={{ marginTop: 8 }}>Light backgrounds look cleanest; dark ones show a faint halo at the hair.</p>
            </>}
          </section>
        </aside>
      </div>
      {sharing && <PublishModal job={sharing} onClose={() => { setSharing(null); refreshRenders(); }} />}
      {cloning && <CloneDialog onClose={(id) => { setCloning(false); refreshVoices(); if (id) update({ provider: "clone", voice: id }); }} />}
    </>
  );
}

function SampleButton({ provider, voiceId, sampleUrl }: { provider: Provider; voiceId: string; sampleUrl?: string | null }) {
  const toast = useToast();
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const audio = useRef<HTMLAudioElement | null>(null);
  const click = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (state === "playing") { audio.current?.pause(); setState("idle"); return; }
    setState("loading");
    try {
      const url = sampleUrl ?? (provider !== "clone" ? (await call(api.POST("/api/v1/voices/sample", { body: { provider, id: voiceId } }))).url : null);
      if (!url) throw new Error("no sample yet");
      audio.current = new Audio(url);
      audio.current.onended = () => setState("idle");
      await audio.current.play();
      setState("playing");
    } catch (err) { setState("idle"); toast((err as Error).message, true); }
  };
  return <button className="icon-btn" onClick={click} aria-label="Play sample">{state === "loading" ? <span className="spinner" style={{ width: 12, height: 12 }} /> : state === "playing" ? icons.pause : icons.play}</button>;
}

function UploadPane({ upload, setUpload }: { upload: { id: string; name: string; seconds: number } | null; setUpload: (u: { id: string; name: string; seconds: number } | null) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const accept = async (f?: File) => {
    if (!f) return;
    setBusy(true);
    try { const rec = await uploadFile(f, "audio"); setUpload({ id: rec.id, name: rec.name, seconds: rec.seconds ?? 0 }); }
    catch (e) { toast((e as Error).message, true); }
    setBusy(false);
  };
  return (
    <div className="composer-pane">
      {upload && <div className="file-item"><div className="grow"><div style={{ fontWeight: 500 }}>{upload.name}</div><div className="small muted">{fmtSeconds(upload.seconds)} · drives the lips</div></div><button className="btn ghost sm" onClick={() => setUpload(null)}>Remove</button></div>}
      <label className="dropzone" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); accept(e.dataTransfer.files[0]); }}>
        <input type="file" accept="audio/*,video/*" hidden onChange={(e) => accept(e.target.files?.[0])} />
        {busy ? <><span className="spinner" style={{ margin: "0 auto 8px" }} />Uploading…</> : <><strong>Drop an audio file</strong> or click to browse<br /><span className="small faint">WAV, MP3, M4A or a video with sound · up to 5 minutes</span></>}
      </label>
    </div>
  );
}

function RecordPane({ upload, setUpload }: { upload: { id: string; name: string; seconds: number } | null; setUpload: (u: { id: string; name: string; seconds: number } | null) => void }) {
  const toast = useToast();
  const [label, setLabel] = useState(upload ? `Recorded ${fmtSeconds(upload.seconds)} · tap to record again` : "Tap to record yourself");
  const [on, setOn] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const toggle = async () => {
    if (recorder.current?.state === "recording") { recorder.current.stop(); return; }
    let stream: MediaStream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch { toast("Microphone not available", true); return; }
    const chunks: Blob[] = [], started = Date.now();
    const rec = new MediaRecorder(stream);
    recorder.current = rec;
    rec.ondataavailable = (e) => chunks.push(e.data);
    const tick = window.setInterval(() => setLabel(`Recording… ${fmtSeconds((Date.now() - started) / 1000)} · tap to stop`), 250);
    rec.onstop = async () => {
      window.clearInterval(tick); stream.getTracks().forEach((t) => t.stop()); setOn(false);
      setLabel("Uploading…");
      try {
        const r = await uploadFile(new File([new Blob(chunks, { type: rec.mimeType || "audio/webm" })], "recording.webm"), "audio");
        setUpload({ id: r.id, name: "recording.webm", seconds: r.seconds ?? 0 });
        setLabel(`Recorded ${fmtSeconds(r.seconds)} · tap to record again`);
      } catch (e) { toast((e as Error).message, true); setLabel("Tap to record yourself"); }
    };
    rec.start(); setOn(true);
  };
  return (
    <div className="composer-pane" style={{ textAlign: "center" }}>
      <button className={`record-btn${on ? " on" : ""}`} onClick={toggle} aria-label="Record"><span /></button>
      <div className="muted">{label}</div>
    </div>
  );
}
