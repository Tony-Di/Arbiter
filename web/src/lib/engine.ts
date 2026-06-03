/* arbiter engine — ported from the mockup's engine.js to TypeScript.
   Owns: category label map, action/severity config, curated mock verdicts,
   a heuristic fallback generator, the moderate() fetch wrapper (live -> mock),
   and span->highlight segmentation. The shared store lives in ../store.ts. */
import type {
  ActionKey,
  Category,
  ContextFlags,
  ModerateOutcome,
  Segment,
  Verdict,
} from "./types";

// 1:1 with the 6 Jigsaw labels — spec §4, no invented categories.
export const CATEGORIES = [
  { key: "toxic", label: "Toxicity", blurb: "Rude, disrespectful, likely to make someone leave." },
  { key: "severe_toxic", label: "Severe toxicity", blurb: "Very hateful, aggressive, or demeaning." },
  { key: "obscene", label: "Obscene", blurb: "Vulgar or profane language." },
  { key: "threat", label: "Threats", blurb: "Intent to inflict harm." },
  { key: "insult", label: "Insult", blurb: "Personal attack or demeaning language." },
  { key: "identity_hate", label: "Hate / identity attack", blurb: "Attacks a protected identity." },
] as const;

const CAT_INDEX: Record<string, number> = Object.fromEntries(
  CATEGORIES.map((c, i) => [c.key, i]),
);

export const catByKey = (k: string) =>
  CATEGORIES[CAT_INDEX[k]] ?? { key: k, label: k, blurb: "" };

export const ACTIONS: Record<
  ActionKey,
  { label: string; token: string; glyph: string; note: string }
> = {
  allow: { label: "Allow", token: "--allow", glyph: "→", note: "Publish without intervention." },
  "human-review": { label: "Human review", token: "--review", glyph: "◷", note: "Route to a human moderator." },
  remove: { label: "Remove", token: "--remove", glyph: "✕", note: "Block from publication." },
};

export const SEVERITY = [
  { word: "none", token: "--sev-0" },
  { word: "low", token: "--sev-1" },
  { word: "medium", token: "--sev-2" },
  { word: "high", token: "--sev-3" },
] as const;

export const sevVar = (n: number) => `var(--sev-${n})`;
export const sevWord = (n: number) => SEVERITY[n]?.word ?? "none";
export const actionVar = (action: ActionKey) => `var(${ACTIONS[action].token})`;

// ---- curated mock verdicts (hand-written for demo + screenshots) ----
function base(): Category[] {
  return CATEGORIES.map((c) => ({ name: c.key, severity: 0, reason: "No signal.", span: null }));
}
function setCat(cats: Category[], key: string, severity: number, reason: string, span?: string | null) {
  const c = cats.find((x) => x.name === key);
  if (c) {
    c.severity = severity;
    c.reason = reason;
    c.span = span ?? null;
  }
  return cats;
}
function flags(o?: ContextFlags): ContextFlags {
  return Object.assign(
    { sarcasm: false, quotation: false, reclaimed: false, direct_threat: false, ambiguity: false, note: null },
    o || {},
  );
}

export interface Sample {
  tag: string;
  text: string;
  build: () => Verdict;
}

export const SAMPLES: Sample[] = [
  {
    tag: "Benign",
    text: "Thanks for the detailed write-up — this actually fixed the bug I'd been stuck on all week.",
    build() {
      const cats = base();
      return { overall_severity: 0, action: "allow", categories: cats, context_flags: flags(), model: "deepseek-chat" };
    },
  },
  {
    tag: "Sarcasm",
    text: "Oh wow, what a 'genius' idea. Said absolutely no one, ever.",
    build() {
      let cats = base();
      cats = setCat(cats, "toxic", 1, "Mocking tone, but no target identity or threat.", "what a 'genius' idea");
      cats = setCat(cats, "insult", 1, "Light derision aimed at an idea, not a person.", null);
      return {
        overall_severity: 1,
        action: "allow",
        categories: cats,
        context_flags: flags({
          sarcasm: true,
          quotation: true,
          note: "Quoted 'genius' reads as sarcasm directed at a proposal, not a person — severity held at low and allowed.",
        }),
        model: "deepseek-chat",
      };
    },
  },
  {
    tag: "Insult + obscene",
    text: "This is absolute garbage and you're an idiot for shipping it without testing.",
    build() {
      let cats = base();
      cats = setCat(cats, "toxic", 2, "Hostile, directed at a person.", "you're an idiot");
      cats = setCat(cats, "insult", 2, "Direct personal insult.", "you're an idiot");
      cats = setCat(cats, "obscene", 1, "Coarse but not profane.", "absolute garbage");
      return {
        overall_severity: 2,
        action: "human-review",
        categories: cats,
        context_flags: flags({
          note: "Personal attack with no protected-class target or threat — borderline, sent to human review.",
        }),
        model: "deepseek-chat",
      };
    },
  },
  {
    tag: "Direct threat",
    text: "If you show up to the meetup again I will find you and make you regret it.",
    build() {
      let cats = base();
      cats = setCat(cats, "threat", 3, "Conditional statement of intent to harm a specific person.", "I will find you and make you regret it");
      cats = setCat(cats, "toxic", 2, "Aggressive and intimidating.", null);
      return {
        overall_severity: 3,
        action: "remove",
        categories: cats,
        context_flags: flags({
          direct_threat: true,
          note: "Credible, targeted threat. direct_threat forces removal regardless of other signals.",
        }),
        model: "deepseek-chat",
      };
    },
  },
  {
    tag: "Identity attack",
    text: "People like you don't belong in this country and never will.",
    build() {
      let cats = base();
      cats = setCat(cats, "identity_hate", 3, "Exclusionary attack on a group based on national/ethnic identity.", "People like you don't belong in this country");
      cats = setCat(cats, "toxic", 2, "Demeaning and hostile.", null);
      cats = setCat(cats, "severe_toxic", 1, "Hateful framing, no slur or threat.", null);
      return {
        overall_severity: 3,
        action: "remove",
        categories: cats,
        context_flags: flags({ note: "Targets a protected identity. Removed." }),
        model: "deepseek-chat",
      };
    },
  },
  {
    tag: "Reclaimed / quoted",
    text: "I'm reporting a comment — someone replied to my post quoting a slur back at me to mock me.",
    build() {
      let cats = base();
      cats = setCat(cats, "identity_hate", 1, "References a slur but in a report/quotation frame, not used as an attack.", "quoting a slur");
      return {
        overall_severity: 1,
        action: "human-review",
        categories: cats,
        context_flags: flags({
          quotation: true,
          reclaimed: true,
          ambiguity: true,
          note: "Term appears inside a report about abuse, not directed at anyone. Quotation downgrades severity; ambiguity routes to human review rather than auto-allow.",
        }),
        model: "deepseek-chat",
      };
    },
  },
];

export function norm(s: string) {
  return (s || "").trim().toLowerCase().replace(/\s+/g, " ");
}

const MOCK_BY_TEXT: Record<string, () => Verdict> = Object.fromEntries(
  SAMPLES.map((s) => [norm(s.text), s.build]),
);

// ---- heuristic generator for arbitrary input (keeps demo working offline) ----
const LEX: Record<string, [RegExp, number, string]> = {
  threat: [/\b(kill|hurt|beat|destroy|find you|make you (pay|regret)|come for you|watch your back)\b/i, 3, "Language signalling intent to harm."],
  identity_hate: [/\b(people like you|your kind|go back to|don't belong|belong here)\b/i, 2, "Exclusionary or identity-targeting language."],
  insult: [/\b(idiot|stupid|moron|dumb|loser|pathetic|clown|incompetent|fool)\b/i, 2, "Personal insult."],
  obscene: [/\b(damn|hell|crap|garbage|trash|sucks)\b/i, 1, "Coarse language."],
  severe_toxic: [/\b(hate you|disgusting|worthless|vile)\b/i, 2, "Strongly demeaning language."],
  toxic: [/\b(shut up|annoying|ridiculous|nonsense|worst|terrible)\b/i, 1, "Generally hostile tone."],
};

function firstSpan(text: string, re: RegExp) {
  const m = text.match(re);
  return m ? m[0] : null;
}

export function generate(text: string): Verdict {
  const cats = base();
  let overall = 0;
  let hadThreat = false;
  for (const c of cats) {
    const rule = LEX[c.name];
    if (!rule) continue;
    const [re, sev, reason] = rule;
    if (re.test(text)) {
      c.severity = sev;
      c.reason = reason;
      c.span = firstSpan(text, re);
      if (sev > overall) overall = sev;
      if (c.name === "threat") hadThreat = true;
    }
  }
  // mild bump: toxic tracks the max of others
  const toxicCat = cats.find((x) => x.name === "toxic")!;
  if (overall > 0 && toxicCat.severity === 0) {
    toxicCat.severity = Math.max(1, overall - 1);
    toxicCat.reason = "Overall hostile tone inferred from other signals.";
  }
  const cf = flags();
  if (/['"].+['"]/.test(text)) cf.quotation = true;
  // deterministic action (mirrors backend: direct_threat upgrades, etc.)
  let action: ActionKey = "allow";
  if (overall >= 3) action = "remove";
  else if (overall === 2) action = "human-review";
  else if (overall === 1) action = "allow";
  if (hadThreat) {
    action = "remove";
    cf.direct_threat = true;
  }
  if (cf.quotation && overall <= 1 && action === "allow") {
    cf.note = "Quotation marks detected — read as quoting rather than asserting; severity held.";
  }
  return { overall_severity: overall, action, categories: cats, context_flags: cf, model: "deepseek-chat" };
}

export class EmptyCommentError extends Error {
  kind = "empty" as const;
}
class ValidationError extends Error {
  kind = "validation" as const;
}

// ---- fetch wrapper: real backend first, mock fallback ----
export async function moderate(comment: string): Promise<ModerateOutcome> {
  const text = (comment || "").trim();
  if (!text) throw new EmptyCommentError("Enter a comment to moderate.");
  try {
    const res = await fetch("/api/moderate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ comment: text }),
    });
    if (res.status === 422) throw new ValidationError("Comment failed server validation (empty).");
    if (!res.ok) throw new Error("Server returned " + res.status);
    const data = (await res.json()) as Verdict;
    return { result: data, source: "live", model: data.model ?? null };
  } catch (e) {
    if (e instanceof ValidationError) throw e; // surface real validation errors
    // network / parse / offline -> deterministic mock
    const mk = MOCK_BY_TEXT[norm(text)];
    const result = mk ? mk() : generate(text);
    return { result, source: "mock", model: result.model ?? null };
  }
}

// ---- span -> highlight segmentation ----
// Collect unique non-null spans, find every occurrence, merge overlaps,
// and return ordered segments: {text, mark, cats:[keys]}.
export function computeSegments(comment: string, categories: Category[]): Segment[] {
  const text = comment || "";
  const spans: { start: number; end: number; key: string }[] = [];
  for (const c of categories) {
    if (!c.span) continue;
    let from = 0;
    let idx: number;
    const needle = c.span;
    while ((idx = text.indexOf(needle, from)) !== -1) {
      spans.push({ start: idx, end: idx + needle.length, key: c.name });
      from = idx + Math.max(1, needle.length);
    }
  }
  if (!spans.length) return [{ text, mark: false, cats: [] }];
  spans.sort((a, b) => a.start - b.start || b.end - a.end);
  const merged: { start: number; end: number; cats: string[] }[] = [];
  for (const s of spans) {
    const last = merged[merged.length - 1];
    if (last && s.start <= last.end) {
      last.end = Math.max(last.end, s.end);
      if (!last.cats.includes(s.key)) last.cats.push(s.key);
    } else {
      merged.push({ start: s.start, end: s.end, cats: [s.key] });
    }
  }
  const segs: Segment[] = [];
  let cur = 0;
  for (const m of merged) {
    if (m.start > cur) segs.push({ text: text.slice(cur, m.start), mark: false, cats: [] });
    segs.push({ text: text.slice(m.start, m.end), mark: true, cats: m.cats.slice() });
    cur = m.end;
  }
  if (cur < text.length) segs.push({ text: text.slice(cur), mark: false, cats: [] });
  return segs;
}
