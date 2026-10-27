import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, Avatar, call } from "../api/client";
import { store, useToast } from "../components/ui";

const SOURCE = { experiment: "Trained", studio: "Trained in Yatta", quick: "Quick avatar" };

export default function Avatars() {
  const toast = useToast();
  const navigate = useNavigate();
  const [avatars, setAvatars] = useState<Avatar[]>([]);
  useEffect(() => { call(api.GET("/api/v1/avatars")).then(setAvatars).catch((e) => toast(e.message, true)); }, [toast]);
  const use = (a: Avatar) => {
    const draft = store.get<{ engine?: string }>("create", {});
    store.set("create", { ...draft, avatar: a.id, feature: a.default_feature, ...(draft.engine && a.engines.includes(draft.engine) ? {} : { engine: a.engines[0] }) });
    navigate("/create");
  };
  return (
    <>
      <div className="page-head">
        <div><div className="eyebrow">顔</div><h1>Avatars</h1><p className="muted">Every face you can speak through. Hover to preview.</p></div>
        <Link className="btn primary" to="/train">New avatar</Link>
      </div>
      <div className="grid">{avatars.map((a) => <AvatarTile key={a.id} avatar={a} onUse={() => use(a)} />)}</div>
    </>
  );
}

function AvatarTile({ avatar: a, onUse }: { avatar: Avatar; onUse: () => void }) {
  const v = a.variants.find((x) => x.feature === a.default_feature) ?? a.variants[0];
  const video = useRef<HTMLVideoElement>(null);
  const [ready, setReady] = useState(false);
  const metrics = v.metrics as { face_psnr?: number; face_lpips?: number };
  return (
    <article className="card tile"
      onMouseEnter={() => video.current?.play().then(() => setReady(true)).catch(() => {})}
      onMouseLeave={() => { video.current?.pause(); setReady(false); }}>
      <div className="media">
        <img alt="" src={v.poster_url ?? ""} />
        {v.preview_url && <video ref={video} className={ready ? "ready" : ""} muted loop playsInline preload="none" src={v.preview_url} />}
        <span className="overlay-badge badge">{SOURCE[a.source]}</span>
      </div>
      <div className="body">
        <h2>{a.name}{a.edition ? ` ${a.edition}` : ""}</h2>
        <p className="small muted">{a.summary}</p>
        {metrics.face_psnr ? <div className="stats"><span>Face PSNR <b className="mono">{metrics.face_psnr.toFixed(1)} dB</b></span>{metrics.face_lpips ? <span>LPIPS <b className="mono">{metrics.face_lpips.toFixed(3)}</b></span> : null}</div> : null}
        {a.source !== "quick" && <div className="chips">{a.variants.map((x) => <span key={x.feature} className={`badge${x.feature === a.default_feature ? " ink" : ""}`}>{x.label}</span>)}</div>}
        <div className="actions"><button className="btn sm primary" onClick={onUse}>Use in Create</button></div>
      </div>
    </article>
  );
}
