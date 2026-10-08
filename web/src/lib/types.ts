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
  language_use?: string;
  evidence_span?: string | null;
  mitigation_categories?: string[];
  [k: string]: boolean | string | string[] | null | undefined;
}

/** The adjudicator's trace when a gray case was escalated (spec 2026-06-08 §8). */
export interface Adjudication {
  policy_version?: string;
  policy_category?: string;
  evidence_span?: string;
  final_action?: ActionKey;
  note?: string | null;
  confidence?: number;
  policies_consulted?: string[];
  precedents_consulted?: string[];
  human?: { action: ActionKey; note?: string | null } | null;
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
  audit?: { policy_version?: string };
  // HITL (spec 2026-06-09 §7): present on live responses; old mocks omit them.
  status?: "final";
  case_id?: string | null;
}

/** /api/moderate now returns a verdict (status "final") OR a pending case. */
export interface PendingCase {
  status: "pending";
  case_id: string;
  comment: string;
  recommendation: {
    policy_version?: string;
    policy_category?: string;
    evidence_span?: string | null;
    recommended_action: string;
    overall_severity: number;
    note?: string | null;
    confidence?: number;
    policies_consulted?: string[];
    precedents_consulted?: string[];
  };
}

/** One row of GET /api/review-queue. */
export interface ReviewCase {
  case_id: string;
  comment: string;
  recommendation: PendingCase["recommendation"];
  created_at: string;
  status?: "pending" | "resolving";
  decision?: { action: ReviewAction; note?: string | null } | null;
}

/** Body of POST /api/review/{case_id} ("confirm" keeps the AI's recommendation). */
export type ReviewAction = "allow" | "remove" | "confirm";

export interface Segment {
  text: string;
  mark: boolean;
  cats: string[];
}

export interface ModerateOutcome {
  result: Verdict | PendingCase;
  source: "live" | "mock";
  model: string | null;
}
