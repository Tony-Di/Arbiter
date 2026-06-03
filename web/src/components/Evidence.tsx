import { Tooltip } from "antd";
import { catByKey } from "../lib/engine";
import type { Segment } from "../lib/types";

/** Original comment with unified-color highlights. Hovering a mark reveals which
 *  categories hit that span (antd Tooltip). */
export function Evidence({
  comment,
  segments,
  mono = true,
}: {
  comment: string;
  segments: Segment[];
  mono?: boolean;
}) {
  if (!comment) return null;
  return (
    <span style={{ fontFamily: mono ? "var(--font-mono)" : "inherit" }}>
      {segments.map((s, i) =>
        s.mark ? (
          <Tooltip key={i} title={s.cats.map((k) => catByKey(k).label).join(" · ")}>
            <mark className="hl">{s.text}</mark>
          </Tooltip>
        ) : (
          <span key={i}>{s.text}</span>
        ),
      )}
    </span>
  );
}
