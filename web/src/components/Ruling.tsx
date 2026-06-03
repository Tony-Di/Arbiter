import { useState, type CSSProperties } from "react";
import { Evidence } from "./Evidence";
import { actionVar, catByKey, computeSegments, sevVar, sevWord } from "../lib/engine";
import { useStore } from "../store";
import type { ActionKey, Category } from "../lib/types";

function Statement({ action }: { action: ActionKey }) {
  const parts: Record<ActionKey, [string, string, string]> = {
    allow: ["This submission is ", "allowed", " to publish."],
    "human-review": ["This submission is held for ", "human review", "."],
    remove: ["This submission is ", "removed", " from publication."],
  };
  const p = parts[action];
  return (
    <div className="vb-statement" style={{ "--ac": actionVar(action) } as CSSProperties}>
      {p[0]}
      <b>{p[1]}</b>
      {p[2]}
    </div>
  );
}

function Finding({ cat }: { cat: Category }) {
  const def = catByKey(cat.name);
  return (
    <div className={"vbf sev-" + cat.severity}>
      <div className="vbf-sev">
        <span className="pip" />
        {sevWord(cat.severity)}
      </div>
      <div className="vbf-body">
        <div className="vbf-name">{def.label}</div>
        <div className="vbf-reason">
          {cat.reason}
          {cat.span && <span className="vbf-span">&ldquo;{cat.span}&rdquo;</span>}
        </div>
      </div>
    </div>
  );
}

const FLAG_LABELS: Record<string, string> = {
  sarcasm: "Sarcasm",
  quotation: "Quotation",
  reclaimed: "Reclaimed",
  reclaimed_slur: "Reclaimed",
  direct_threat: "Direct threat",
  ambiguity: "Ambiguous",
};

export function Ruling() {
  const state = useStore();
  const [open, setOpen] = useState(false);
  const r = state.result;
  if (!r) return null;

  const segs = computeSegments(state.comment, r.categories);
  const flagged = r.categories.filter((c) => c.severity > 0).sort((a, b) => b.severity - a.severity);
  const clear = r.categories.filter((c) => c.severity === 0);
  const cf = r.context_flags;
  const trueFlags = Object.entries(cf)
    .filter(([k, v]) => k !== "note" && v === true)
    .map(([k]) => k);

  return (
    <div className="vb-ruling">
      <div className="vb-headline">
        <span className="lead">Ruling</span>
        <Statement action={r.action} />
        <div className="vb-meta">
          <div className="m">
            <div className="k">Overall severity</div>
            <div className="v" style={{ color: sevVar(r.overall_severity) }}>
              {sevWord(r.overall_severity)}
            </div>
          </div>
          <div className="m">
            <div className="k">Categories flagged</div>
            <div className="v" style={{ textTransform: "none" }}>
              {flagged.length} of 6
            </div>
          </div>
        </div>
      </div>

      <div className="vb-evi-wrap">
        <div className="vb-cap">Comment under review</div>
        <div className="vb-evi">
          <Evidence comment={state.comment} segments={segs} mono={false} />
        </div>
      </div>

      <div>
        <div className="vb-cap">Findings</div>
        <div className="vb-find">
          {flagged.map((c) => (
            <Finding key={c.name} cat={c} />
          ))}
          {clear.length > 0 && (
            <>
              <div className={"vb-clear" + (open ? " open" : "")} onClick={() => setOpen((o) => !o)}>
                <span className="tw">&#9656;</span>
                {clear.length} categor{clear.length === 1 ? "y" : "ies"} returned no signal ·{" "}
                {clear.map((c) => catByKey(c.name).label).join(", ")}
              </div>
              {open && clear.map((c) => <Finding key={c.name} cat={c} />)}
            </>
          )}
        </div>
      </div>

      <div className="vb-notes">
        <div className="nh">Gray-area reasoning</div>
        <div className="vb-fl">
          {trueFlags.length ? (
            trueFlags.map((f) => (
              <span key={f} className="vb-f" data-hot={f === "direct_threat"}>
                {FLAG_LABELS[f] ?? f}
              </span>
            ))
          ) : (
            <span className="vb-f-none">No context modifiers fired.</span>
          )}
        </div>
        {cf.note && <div className="vb-note-txt">{cf.note}</div>}
      </div>
    </div>
  );
}
