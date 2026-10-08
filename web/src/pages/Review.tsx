/* Review queue — the arbiter "docket" (HITL spec 2026-06-09 §8).
   Hairline-separated rows, a confidence meter, semantic action chips, and an
   inline drawer with the adjudicator's reasoning. Resolving a case keeps the
   row visible (dimmed, with a resolved pill) until the next refresh — the
   moderator sees what they just ruled. Styles: variant-b.css (rq-*). */
import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { ACTIONS, fetchQueue, resolveCase } from "../lib/engine";
import type { ActionKey, ReviewAction, ReviewCase } from "../lib/types";

function confColor(c: number) {
  // high confidence the model is right -> calmer; low -> warmer (needs eyes)
  if (c >= 0.8) return "var(--allow)";
  if (c >= 0.6) return "var(--review)";
  return "var(--remove)";
}

function relTime(iso: string) {
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!Number.isFinite(d) || d < 60) return "just now";
  if (d < 3600) return Math.floor(d / 60) + "m ago";
  if (d < 86400) return Math.floor(d / 3600) + "h ago";
  return Math.floor(d / 86400) + "d ago";
}

type Resolved = "confirmed" | "allowed" | "removed";

function RQRow({
  item,
  resolved,
  busy,
  onRule,
}: {
  item: ReviewCase;
  resolved: Resolved | null;
  busy: boolean;
  onRule: (caseId: string, action: ReviewAction, mark: Resolved) => void;
}) {
  const [open, setOpen] = useState(false);
  const rec = item.recommendation;
  const act = ACTIONS[(rec.recommended_action as ActionKey)] ?? ACTIONS["human-review"];
  const conf = rec.confidence;

  const resolvedMeta = resolved
    ? {
        confirmed: { word: "Confirmed AI", token: act.token },
        allowed: { word: "Allowed", token: "--allow" },
        removed: { word: "Removed", token: "--remove" },
      }[resolved]
    : null;

  return (
    <div className="rq-item" data-open={open} data-resolved={!!resolved}>
      <div className="rq-row-main" onClick={() => setOpen((o) => !o)}>
        <div className="rq-c">
          <span className="rq-tw">&#9656;</span>
          <span className="rq-ct">{item.comment}</span>
        </div>

        <span className="rq-rec" style={{ "--ac": `var(${act.token})` } as CSSProperties}>
          <span className="g">{act.glyph}</span>
          {act.label}
        </span>

        <div
          className="rq-conf"
          style={{ "--cc": conf != null ? confColor(conf) : "var(--tx-3)" } as CSSProperties}
        >
          <div className="track">
            <div className="fill" style={{ width: conf != null ? Math.round(conf * 100) + "%" : 0 }} />
          </div>
          <span className="num">{conf != null ? conf.toFixed(2) + " confidence" : "no confidence reported"}</span>
        </div>

        <span className="rq-when" title={item.created_at}>
          {relTime(item.created_at)}
        </span>

        {resolvedMeta ? (
          <span
            className="rq-done"
            style={{ "--rc": `var(${resolvedMeta.token})` } as CSSProperties}
            onClick={(e) => e.stopPropagation()}
          >
            <span className="dot" />
            {resolvedMeta.word}
          </span>
        ) : item.decision ? (
          <span className="rq-act" onClick={(e) => e.stopPropagation()}>
            <button className="rq-btn primary" disabled={busy}
              onClick={() => onRule(item.case_id, item.decision!.action,
                item.decision!.action === "remove" ? "removed" : item.decision!.action === "allow" ? "allowed" : "confirmed")}>
              Retry saving {item.decision.action}
            </button>
          </span>
        ) : (
          <span className="rq-act" onClick={(e) => e.stopPropagation()}>
            {/* "Confirm AI" is circular when the AI's recommendation IS
                human-review (the reviewer is the human) -- degraded/step-limit
                cases only offer the two real rulings. */}
            {rec.recommended_action !== "human-review" && (
              <button
                className="rq-btn primary"
                disabled={busy}
                style={{ "--ac": `var(${act.token})` } as CSSProperties}
                onClick={() => onRule(item.case_id, "confirm", "confirmed")}
              >
                Confirm
              </button>
            )}
            <button className="rq-btn" disabled={busy} onClick={() => onRule(item.case_id, "allow", "allowed")}>
              Allow
            </button>
            <button className="rq-btn danger" disabled={busy} onClick={() => onRule(item.case_id, "remove", "removed")}>
              Remove
            </button>
          </span>
        )}
      </div>

      {open && (
        <div className="rq-drawer">
          <div className="rq-drawer-inner">
            <div className="vb-evi-wrap">
              <div className="vb-cap">Comment under review</div>
              <div className="vb-evi">{item.comment}</div>
            </div>
            <div className="vb-notes">
              <div className="nh">Reason for review</div>
              <div className="vb-fl">
                {rec.policies_consulted?.length || rec.precedents_consulted?.length ? (
                  <>
                    {rec.policies_consulted?.map((p) => (
                      <span key={"p" + p} className="vb-f">
                        policy &middot; {p}
                      </span>
                    ))}
                    {rec.precedents_consulted?.map((q) => (
                      <span key={"q" + q} className="vb-f">
                        precedent &middot; {q}
                      </span>
                    ))}
                  </>
                ) : (
                  <span className="vb-f-none">No additional policy or precedent lookup.</span>
                )}
              </div>
              {rec.note && <div className="vb-note-txt">{rec.note}</div>}
              {rec.evidence_span && <div className="vb-note-txt">Evidence: &ldquo;{rec.evidence_span}&rdquo;</div>}
              {rec.policy_version && <div className="vb-f-none">Policy {rec.policy_version}</div>}
              {item.decision && <div className="vb-note-txt">Your {item.decision.action} decision is recorded. Retry to finish saving it.</div>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Review({ onCount }: { onCount?: (n: number) => void }) {
  const [cases, setCases] = useState<ReviewCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolved, setResolved] = useState<Record<string, Resolved>>({});
  const [busyId, setBusyId] = useState<string | null>(null);

  const pending = cases.filter((c) => !resolved[c.case_id]).length;

  useEffect(() => {
    onCount?.(pending);
  }, [pending, onCount]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setCases(await fetchQueue());
      setResolved({});
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the queue.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const onRule = useCallback(async (caseId: string, action: ReviewAction, mark: Resolved) => {
    setError(null);
    setBusyId(caseId);
    try {
      const saved = cases.find((c) => c.case_id === caseId)?.decision;
      await resolveCase(caseId, action, saved?.note ?? null);
      setResolved((r) => ({ ...r, [caseId]: mark }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to resolve the case.");
      try { setCases(await fetchQueue(false)); } catch { /* Keep real rows while disconnected. */ }
    } finally {
      setBusyId(null);
    }
  }, [cases]);

  return (
    <div className="rq">
      <div className="rq-head">
        <div className="t">
          Review queue<span className="n">{pending}</span>
        </div>
        <div className="sub">Comments requiring a human decision under the moderation policy.</div>
        <button className="rq-btn" onClick={refresh} disabled={loading || busyId !== null}>Refresh queue</button>
      </div>

      {error && <div className="vb-err">{error}</div>}

      {loading ? (
        <div className="rq-empty">Loading the docket…</div>
      ) : cases.length === 0 ? (
        <div className="rq-empty">
          <div className="big">No cases waiting for review.</div>
          Policy review cases and uncertain rulings appear here.
        </div>
      ) : (
        <>
          <div className="rq-cols">
            <span>Comment</span>
            <span>AI recommends</span>
            <span>Confidence</span>
            <span>Received</span>
            <span style={{ justifySelf: "end" }}>Ruling</span>
          </div>

          <div className="rq-list">
            {cases.map((it) => (
              <RQRow
                key={it.case_id}
                item={it}
                resolved={resolved[it.case_id] ?? null}
                busy={busyId === it.case_id}
                onRule={onRule}
              />
            ))}
          </div>

          <div className="rq-foot">
            <span className="rq-count">
              {pending} of {cases.length} pending cases
            </span>
            <span className="rq-page">
              <button className="rq-pg" disabled>
                &lsaquo;
              </button>
              <button className="rq-pg" aria-current="true">
                1
              </button>
              <button className="rq-pg" disabled>
                &rsaquo;
              </button>
            </span>
          </div>
        </>
      )}
    </div>
  );
}
