import { ReactNode, useMemo, useState } from "react";
import { Modal } from "./ui";

export interface Choice {
  id: string;
  title: ReactNode;
  sub?: ReactNode;
  detail?: ReactNode; // optional second, fainter line
  lead?: ReactNode; // thumbnail or chip before the text
  trailing?: ReactNode; // e.g. a sample play button
  search: string; // text the search box matches
  note?: string; // shown instead of `sub` and dimmed, but still selectable (e.g. "Needs a trained avatar")
  disabled?: boolean; // not selectable (e.g. a voice still preparing)
}

/** The first `limit` choices first, with the selected one always among them. */
export function visibleChoices(choices: Choice[], selected: string | undefined, limit: number) {
  const top = choices.slice(0, limit);
  const picked = choices.find((c) => c.id === selected);
  if (!picked || top.some((c) => c.id === picked.id)) return top;
  return [...top.slice(0, Math.max(0, limit - 1)), picked];
}

function Row({ choice, selected, onSelect }: { choice: Choice; selected: boolean; onSelect: () => void }) {
  return (
    <div className={`option${selected ? " selected" : ""}${choice.disabled ? " disabled" : ""}${choice.note ? " muted-choice" : ""}`}
      role="button" tabIndex={choice.disabled ? -1 : 0} aria-pressed={selected} aria-disabled={choice.disabled}
      onClick={() => !choice.disabled && onSelect()}
      onKeyDown={(e) => { if (!choice.disabled && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onSelect(); } }}>
      {choice.lead}
      <span className="grow"><span className="title">{choice.title}</span>
        {(choice.note || choice.sub) && <span className="sub">{choice.note ?? choice.sub}</span>}
        {choice.detail && <span className="sub faint">{choice.detail}</span>}</span>
      {choice.trailing}
    </div>
  );
}

/** A short list (top `limit`) with "Browse all" opening a searchable, scrollable list of every choice. */
export function ChoiceList({ choices, selected, onSelect, limit = 4, noun, empty }: {
  choices: Choice[]; selected?: string; onSelect: (id: string) => void; limit?: number; noun: string; empty?: ReactNode;
}) {
  const [browsing, setBrowsing] = useState(false);
  const [query, setQuery] = useState("");
  const shown = visibleChoices(choices, selected, limit);
  const matches = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    return choices.filter((c) => words.every((w) => c.search.toLowerCase().includes(w)));
  }, [choices, query]);
  if (!choices.length) return <>{empty}</>;
  return (
    <>
      <div className="picker">
        {shown.map((c) => <Row key={c.id} choice={c} selected={c.id === selected} onSelect={() => onSelect(c.id)} />)}
      </div>
      {choices.length > limit && (
        <button className="btn ghost sm browse-all" onClick={() => { setQuery(""); setBrowsing(true); }}>Browse all {choices.length} {noun}</button>
      )}
      {browsing && (
        <Modal onClose={() => setBrowsing(false)}>
          <div className="modal-body">
            <h2>Choose {noun.replace(/s$/, "")}</h2>
            <input className="input" type="search" placeholder={`Search ${noun}`} aria-label={`Search ${noun}`} value={query} autoFocus
              onChange={(e) => setQuery(e.target.value)} />
            <div className="choice-modal-list">
              {matches.length ? matches.map((c) => (
                <Row key={c.id} choice={c} selected={c.id === selected} onSelect={() => { onSelect(c.id); setBrowsing(false); }} />
              )) : <p className="small muted">No {noun} match “{query}”.</p>}
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}
