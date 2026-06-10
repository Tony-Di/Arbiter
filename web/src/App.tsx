import { useEffect, useState } from "react";
import { Button, Input } from "antd";
import { Ruling } from "./components/Ruling";
import Review from "./pages/Review";
import { fetchQueue, SAMPLES } from "./lib/engine";
import { store, useStore } from "./store";

type View = "moderate" | "review";

export default function App({ split = true }: { split?: boolean }) {
  const state = useStore();
  const loading = state.status === "loading";
  // HITL (spec 2026-06-09 §8): two views, no router -- masthead pill tabs.
  const [view, setView] = useState<View>("moderate");
  const [queueCount, setQueueCount] = useState<number | null>(null);

  // Count for the Review tab badge; refreshed by <Review/> while it's mounted.
  useEffect(() => {
    fetchQueue()
      .then((cs) => setQueueCount(cs.length))
      .catch(() => {});
  }, []);

  return (
    <div
      className={
        "vb" + (split && view === "moderate" ? " split" : "") + (view === "review" ? " review" : "")
      }
    >
      <div className="vb-scroll">
        <div className="vb-mast">
          {/* "Panel of Six" mark — 6 classifiers, amber = the verdict */}
          <svg className="vb-mark" viewBox="0 0 200 200" role="img" aria-label="arbiter mark">
            <circle cx="100" cy="100" r="72" fill="none" stroke="#ECEFF2" strokeOpacity="0.10" strokeWidth="2.4" />
            <circle cx="100" cy="28" r="14.4" fill="#9AA5B1" />
            <circle cx="162.35" cy="64" r="16.6" fill="#E7A33C" />
            <circle cx="162.35" cy="136" r="14.4" fill="#9AA5B1" />
            <circle cx="100" cy="172" r="14.4" fill="#9AA5B1" />
            <circle cx="37.65" cy="136" r="14.4" fill="#9AA5B1" />
            <circle cx="37.65" cy="64" r="14.4" fill="#9AA5B1" />
            <circle cx="100" cy="100" r="9" fill="#ECEFF2" />
          </svg>
          <span className="nm">
            arbiter<i>.</i>
          </span>
          <span className="sub">adjudication of user comments</span>
          <div className="vb-tabs" role="tablist">
            <button
              className="vb-tab"
              role="tab"
              aria-selected={view === "moderate"}
              onClick={() => setView("moderate")}
            >
              Moderate
            </button>
            <button
              className="vb-tab"
              role="tab"
              aria-selected={view === "review"}
              onClick={() => setView("review")}
            >
              Review
              {queueCount != null && queueCount > 0 && <span className="ct">{queueCount}</span>}
            </button>
          </div>
        </div>

        {view === "review" && <Review onCount={setQueueCount} />}

        {view === "moderate" && (
          <>
        <div className="vb-sub">
          <div className="vb-cap">Submission</div>
          <Input.TextArea
            className="vb-ta"
            variant="borderless"
            placeholder="Paste a comment to moderate…"
            autoSize={{ minRows: 4 }}
            value={state.comment}
            onChange={(e) => store.setComment(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) store.submit();
            }}
          />
          <div className="vb-row">
            {SAMPLES.map((s) => (
              <Button
                key={s.tag}
                className="vb-chip"
                onClick={() => {
                  store.setComment(s.text);
                  store.submit(s.text);
                }}
              >
                {s.tag}
              </Button>
            ))}
            <Button
              className="vb-run"
              disabled={loading || !state.comment.trim()}
              onClick={() => store.submit()}
            >
              {loading ? (
                <>
                  <span className="vb-spin" /> Adjudicating…
                </>
              ) : (
                "Submit for ruling"
              )}
            </Button>
          </div>
        </div>

        <div className="vb-rule-line" />

        <div className="vb-main">
          {state.status === "idle" && (
            <div className="vb-empty">No ruling yet — submit a comment to begin.</div>
          )}
          {state.status === "loading" && (
            <div className="vb-empty">Weighing the six categories…</div>
          )}
          {state.status === "error" && <div className="vb-err">{state.error}</div>}
          {state.status === "pending" && state.pending && (
            <div className="vb-empty">
              <p>
                Sent to human review — the adjudicator wasn't confident enough to
                rule alone
                {state.pending.recommendation.confidence != null && (
                  <> (confidence {state.pending.recommendation.confidence})</>
                )}
                . It recommends <b>{state.pending.recommendation.recommended_action}</b>.
              </p>
              <Button onClick={() => setView("review")}>Open the review queue</Button>
            </div>
          )}
          {state.status === "done" && <Ruling />}
        </div>
          </>
        )}
      </div>
    </div>
  );
}
