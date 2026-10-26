import { useCallback, useEffect, useRef, useState } from "react";
import { api, call, uploadFile, VoiceCatalogue } from "../api/client";
import { chipColor, fmtSeconds, icons, Modal, usePoll, useToast } from "../components/ui";

export default function Voices() {
  const toast = useToast();
  const [voices, setVoices] = useState<VoiceCatalogue | null>(null);
  const [cloning, setCloning] = useState(false);
  const refresh = useCallback(() => call(api.GET("/api/v1/voices")).then(setVoices).catch((e) => toast(e.message, true)), [toast]);
  useEffect(() => { refresh(); }, [refresh]);
  usePoll(refresh, 5000, !!voices?.clone.some((v) => v.state === "preparing"));
  const remove = async (id: string, name: string) => {
    if (!confirm(`Delete the cloned voice “${name}”?`)) return;
    await call(api.DELETE("/api/v1/voices/clones/{voice_id}", { params: { path: { voice_id: id } } }));
    refresh();
  };
  return (
    <>
      <div className="page-head">
        <div><div className="eyebrow">声</div><h1>Voices</h1><p className="muted">Clone a voice from 10–15 seconds of speech, or use a stock voice.</p></div>
        <button className="btn primary" onClick={() => setCloning(true)}>＋ Clone a voice</button>
      </div>
      <div className="section-label"><span>My voices<span className="kanji">私の声</span></span><span className="faint small">F5-TTS · runs on this server</span></div>
      {voices?.clone.length ? (
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", marginBottom: 32 }}>
          {voices.clone.map((v) => (
            <div key={v.id} className="card panel" style={{ gap: 10 }}>
              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <span className="chip" style={{ background: chipColor(v.id), width: 36, height: 36, fontSize: 16 }}>{v.name[0]}</span>
                <div className="grow" style={{ flex: 1 }}><h2>{v.name}</h2><div className="small muted">{v.state === "ready" ? "Ready" : v.state === "preparing" ? "Preparing…" : v.detail}</div></div>
                {v.sample_url && <audio src={v.sample_url} controls style={{ width: 120, height: 32 }} />}
              </div>
              <div><button className="btn ghost sm danger" onClick={() => remove(v.id, v.name)}>Delete</button></div>
            </div>
          ))}
        </div>
      ) : <div className="empty" style={{ marginBottom: 32 }}><h2>No cloned voices yet</h2><p>Record yourself for 10–15 seconds and Yatta speaks any script in your voice.</p></div>}
      <div className="section-label"><span>Stock voices<span className="kanji">標準</span></span><span className="faint small">ElevenLabs · Meta MMS</span></div>
      <div className="card">{[...(voices?.elevenlabs ?? []), ...(voices?.mms ?? [])].map((v) => (
        <div key={v.id} className="job-row">
          <span className="chip" style={{ background: chipColor(v.id) }}>{v.name[0]}</span>
          <div className="grow"><div className="title">{v.name}</div><div className="small muted">{[v.gender, v.accent, v.style].filter(Boolean).join(" · ")}</div></div>
        </div>
      ))}</div>
      {cloning && <CloneDialog onClose={() => { setCloning(false); refresh(); }} />}
    </>
  );
}

export function CloneDialog({ onClose }: { onClose: (voiceId?: string) => void }) {
  const toast = useToast();
  const [name, setName] = useState("My voice");
  const [text, setText] = useState("");
  const [consent, setConsent] = useState(false);
  const [upload, setUpload] = useState<{ id: string; seconds: number } | null>(null);
  const [status, setStatus] = useState("Tap to record, or");
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const accept = async (file: File) => {
    setStatus("Uploading…");
    try {
      const rec = await uploadFile(file, "audio");
      setUpload({ id: rec.id, seconds: rec.seconds ?? 0 });
      const s = rec.seconds ?? 0;
      setStatus(`${fmtSeconds(s)} ready${s > 20 ? " · the first ~12 s are used" : s < 5 ? " · a bit short, 10 s is better" : ""}`);
    } catch (e) { setStatus((e as Error).message); }
  };
  const record = async () => {
    if (recorder.current?.state === "recording") { recorder.current.stop(); return; }
    let stream: MediaStream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { setStatus("Microphone not available"); return; }
    const chunks: Blob[] = [], started = Date.now();
    const rec = new MediaRecorder(stream);
    recorder.current = rec;
    rec.ondataavailable = (e) => chunks.push(e.data);
    const tick = window.setInterval(() => setStatus(`Recording ${fmtSeconds((Date.now() - started) / 1000)} · tap to stop`), 250);
    rec.onstop = () => {
      window.clearInterval(tick); stream.getTracks().forEach((t) => t.stop()); setOn(false);
      accept(new File([new Blob(chunks, { type: rec.mimeType || "audio/webm" })], "voice.webm"));
    };
    rec.start(); setOn(true);
  };
  const go = async () => {
    if (!upload) return;
    setBusy(true);
    try {
      const v = await call(api.POST("/api/v1/voices/clones", { body: { name, upload: upload.id, consent, text: text || null } }));
      toast("Cloning the voice — about a minute");
      onClose(v.id);
    } catch (e) { toast((e as Error).message, true); setBusy(false); }
  };
  return (
    <Modal onClose={() => onClose()}>
      <div className="modal-body">
        <h2>Clone a voice</h2>
        <p className="small muted">Record or upload 10–15 seconds of clear speech in a quiet room, the way the voice should sound. Only clone your own voice, or a voice whose owner agreed.</p>
        <label className="label">Name<input className="input" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} /></label>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <button className={`record-btn${on ? " on" : ""}`} style={{ width: 56, height: 56, margin: 0 }} onClick={record} aria-label="Record"><span /></button>
          <span className="small muted">{status}</span>
          <label className="btn sm">{icons.download}Upload<input type="file" accept="audio/*,video/*" hidden onChange={(e) => e.target.files?.[0] && accept(e.target.files[0])} /></label>
        </div>
        <label className="label">What is said in the recording (optional; transcribed automatically)
          <textarea className="input" rows={2} value={text} onChange={(e) => setText(e.target.value)} /></label>
        <label className="check"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} /> This is my voice, or the speaker agreed to be cloned.</label>
      </div>
      <div className="modal-actions">
        <button className="btn" onClick={() => onClose()}>Cancel</button>
        <button className="btn primary" disabled={!upload || !consent || busy} onClick={go}>Clone voice</button>
      </div>
    </Modal>
  );
}
