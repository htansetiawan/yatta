import { useState } from "react";
import { api, call, Render } from "../api/client";
import { fmtSeconds, icons, Modal, timeAgo, useToast } from "./ui";

export const STATE_LABEL: Record<string, string> = {
  queued: "Queued", voicing: "Generating speech", features: "Reading the speech", waiting_gpu: "Waiting for GPU",
  rendering: "Rendering", encoding: "Encoding", done: "Ready", failed: "Failed", cancelled: "Cancelled",
};
const STATE_PROGRESS: Record<string, number> = { queued: 4, voicing: 15, features: 32, waiting_gpu: 40, rendering: 60, encoding: 92, done: 100 };
export const FEATURE_LABEL: Record<string, string> = {
  deepspeech: "DeepSpeech", esperanto: "wav2vec2 · Esperanto", hubert: "HuBERT", whisper: "Whisper", latentsync: "LatentSync",
};
export const isActive = (j: Render) => !["done", "failed", "cancelled"].includes(j.state);

export function jobEngine(j: Render) {
  const engine = j.engine === "latentsync" ? "Realistic" : `Fast · ${FEATURE_LABEL[j.feature] ?? j.feature}`;
  return j.voice?.provider === "clone" ? `${engine} · cloned voice` : engine;
}

export function JobRow({ job, onPlay, onCheckGpu }: { job: Render; onPlay?: () => void; onCheckGpu?: () => void }) {
  const active = isActive(job);
  const indeterminate = ["waiting_gpu", "rendering", "voicing", "features"].includes(job.state);
  return (
    <div className="job-row">
      {job.state === "done" ? <img className="thumb" alt="" src={job.poster_url ?? ""} />
        : <div className="thumb" style={{ display: "grid", placeItems: "center" }}>{active && <span className="spinner" />}</div>}
      <div className="grow">
        <div className="title">{job.title}</div>
        <div className="small muted">{job.avatar_name} · {jobEngine(job)} · {timeAgo(job.created)}{job.state === "done" ? ` · ${fmtSeconds(job.duration)}` : ""}</div>
        {active && <>
          <div className={`progress${indeterminate ? " indeterminate" : ""}`}><span style={{ width: `${STATE_PROGRESS[job.state] ?? 5}%` }} /></div>
          <div className="small faint" style={{ marginTop: 4 }}>{job.detail || STATE_LABEL[job.state]}
            {job.state === "waiting_gpu" && onCheckGpu && <> · <button className="btn ghost sm" style={{ height: 22, padding: "0 6px" }} onClick={onCheckGpu}>check now</button></>}
          </div>
        </>}
        {job.state === "failed" && <div className="small" style={{ color: "var(--shu-ink)", marginTop: 4 }}>{job.detail}</div>}
      </div>
      {job.state === "done" ? <button className="btn sm ghost" onClick={onPlay}>{icons.play}Play</button>
        : <span className={`badge ${job.state === "failed" ? "shu" : active ? "warn" : ""}`}>{STATE_LABEL[job.state] ?? job.state}</span>}
    </div>
  );
}

export function PublishModal({ job: initial, onClose }: { job: Render; onClose: (job: Render) => void }) {
  const [job, setJob] = useState(initial);
  const [title, setTitle] = useState(initial.title);
  const toast = useToast();
  const link = job.watch_url ? `${location.origin}${job.watch_url}` : "";
  const publish = async () => {
    try { setJob(await call(api.POST("/api/v1/renders/{job_id}/publish", { params: { path: { job_id: job.id } }, body: { title } }))); }
    catch (e) { toast((e as Error).message, true); }
  };
  const unpublish = async () => setJob(await call(api.POST("/api/v1/renders/{job_id}/unpublish", { params: { path: { job_id: job.id } } })));
  const copy = async () => { try { await navigator.clipboard.writeText(link); toast("Link copied"); } catch { toast("Copy failed — select the link", true); } };
  return (
    <Modal onClose={() => onClose(job)}>
      <div className="modal-body">
        <h2>Share</h2>
        <video src={job.video_url ?? ""} poster={job.poster_url ?? ""} controls playsInline style={{ maxHeight: 300, objectFit: "contain" }} />
        <label className="label">Title<input className="input" value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} disabled={!!job.watch_url} /></label>
        {job.watch_url ? <>
          <div className="copy-row"><input className="input" readOnly value={link} /><button className="btn sm" onClick={copy}>Copy</button><a className="btn sm" href={job.watch_url} target="_blank">Open</a></div>
          <p className="small faint">Anyone with this link can watch the video, without the access key. Previews show in iMessage and WhatsApp.</p>
        </> : <p className="small muted">Creates a public page for this video at {location.host}/watch/…</p>}
      </div>
      <div className="modal-actions">
        {job.watch_url && <button className="btn ghost" onClick={unpublish}>Unpublish</button>}
        <button className="btn" onClick={() => onClose(job)}>Close</button>
        {!job.watch_url && <button className="btn primary" onClick={publish}>Create share link</button>}
      </div>
    </Modal>
  );
}

export function PlayModal({ job, onClose }: { job: Render; onClose: () => void }) {
  return (
    <Modal onClose={onClose}>
      <div className="modal-body">
        <h2>{job.title}</h2>
        <video src={job.video_url ?? ""} poster={job.poster_url ?? ""} controls autoPlay playsInline />
        {job.text && <p className="small muted">{job.text}</p>}
      </div>
      <div className="modal-actions"><button className="btn" onClick={onClose}>Close</button></div>
    </Modal>
  );
}
