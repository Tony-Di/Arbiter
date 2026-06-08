export type ActionKey = "allow" | "human-review" | "remove";

export interface Category {
  name: string;
  severity: number; // ordinal 0..3
  reason: string;
  span: string | null;
}

/** Modifier booleans from the context node + an optional note.
 *  The mock uses `reclaimed`; the live backend uses `reclaimed_slur` — both supported. */
export interface ContextFlags {
  sarcasm?: boolean;
  quotation?: boolean;
  reclaimed?: boolean;
  reclaimed_slur?: boolean;
  direct_threat?: boolean;
  ambiguity?: boolean;
  note?: string | null;
  [k: string]: boolean | string | null | undefined;
}

/** The adjudicator's trace when a gray case was escalated (spec 2026-06-08 §8). */
export interface Adjudication {
  final_action?: ActionKey;
  note?: string | null;
  policies_consulted?: string[];
}

/** Shape returned by POST /api/moderate (model is optional — backend may omit it). */
export interface Verdict {
  overall_severity: number;
  action: ActionKey;
  categories: Category[];
  context_flags: ContextFlags;
  model?: string | null;
  escalated?: boolean;
  adjudication?: Adjudication | null;
}

export interface Segment {
  text: string;
  mark: boolean;
  cats: string[];
}

export interface ModerateOutcome {
  result: Verdict;
  source: "live" | "mock";
  model: string | null;
}
