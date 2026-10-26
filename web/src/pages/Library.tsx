import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, call, Render } from "../api/client";
import { fmtSeconds, icons, timeAgo, usePoll, useToast } from "../components/ui";
import { isActive, jobEngine, PlayModal, PublishModal, STATE_LABEL } from "../components/renders";

export default function Library() {
  const toast = useToast();
  const [items, setItems] = useState<Render[]>([]);
  const [playing, setPlaying] = useState<Render | null>(null);
  const [sharing, setSharing] = useState<Render | null>(null);
  const refresh = useCallback(() => call(api.GET("/api/v1/renders")).then(setItems).catch((e) => toast(e.message, true)), [toast]);
  useEffect(() => { refresh(); }, [refresh]);
  usePoll(refresh, 5000, items.some(isActive));
  const remove = async (j: Render) => {
    if (!confirm("Delete this video? This cannot be undone.")) return;
    try { await call(api.DELETE("/api/v1/renders/{job_id}", { params: { path: { job_id: j.id } } })); refresh(); }
    catch (e) { toast((e as Error).message, true); }
  };
  return (
    <>
      <div className="page-head">
        <div><div className="eyebrow">作品</div><h1>Library</h1><p className="muted">Everything you have made. Share a video to get a link that plays anywhere.</p></div>
        <Link className="btn shu" to="/create">{icons.spark}New video</Link>
      </div>
      {items.length ? <div className="grid">{items.map((j) => (
        <article key={j.id} className="card tile">
          <div className="media">
            {j.state === "done" ? <><img alt="" src={j.poster_url ?? ""} /><button className="play-overlay" onClick={() => setPlaying(j)} aria-label="Play">{icons.bigPlay}</button></>
              : <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>{j.state === "failed" ? <span className="badge shu">Failed</span> : <span className="spinner" />}</div>}
            {j.watch_url && <span className="overlay-badge badge ok">Shared</span>}
          </div>
          <div className="body">
            <h2 style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{j.title}</h2>
            <p className="small muted">{j.avatar_name} · {jobEngine(j)}<br />{timeAgo(j.created)}{j.duration ? ` · ${fmtSeconds(j.duration)}` : ""}{j.state !== "done" ? ` · ${STATE_LABEL[j.state] ?? j.state}` : ""}</p>
            {j.state === "failed" && <p className="small" style={{ color: "var(--shu-ink)" }}>{j.detail}</p>}
            <div className="actions">
              {j.state === "done" && <><a className="btn sm" href={j.video_url ?? ""} download aria-label="Download">{icons.download}</a><button className="btn sm" onClick={() => setSharing(j)}>{icons.share}Share</button></>}
              {!isActive(j) && <button className="btn sm ghost danger" onClick={() => remove(j)}>Delete</button>}
            </div>
          </div>
        </article>
      ))}</div> : <div className="empty"><h2>Nothing yet</h2><p>Write a script on Create and your videos collect here.</p><p style={{ marginTop: 16 }}><Link className="btn primary" to="/create">Make a video</Link></p></div>}
      {playing && <PlayModal job={playing} onClose={() => setPlaying(null)} />}
      {sharing && <PublishModal job={sharing} onClose={() => { setSharing(null); refresh(); }} />}
    </>
  );
}
