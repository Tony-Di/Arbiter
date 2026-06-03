import { Button, Input } from "antd";
import { Ruling } from "./components/Ruling";
import { SAMPLES } from "./lib/engine";
import { store, useStore } from "./store";

const SOURCE_LABEL: Record<string, string> = { live: "live", mock: "mock" };

export default function App({ split = true }: { split?: boolean }) {
  const state = useStore();
  const loading = state.status === "loading";
  const src = state.source ?? "idle";

  return (
    <div className={"vb" + (split ? " split" : "")}>
      <div className="vb-scroll">
        <div className="vb-mast">
          <span className="nm">
            arbiter<i>.</i>
          </span>
          <span className="sub">adjudication of user comments</span>
          <span className="src" data-src={src}>
            <span className="d" />
            {SOURCE_LABEL[src] ?? "standby"}
          </span>
        </div>

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
          {state.status === "done" && <Ruling />}
        </div>
      </div>
    </div>
  );
}
