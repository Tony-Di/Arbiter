import { useSyncExternalStore } from "react";
import { EmptyCommentError, moderate } from "./lib/engine";
import type { Verdict } from "./lib/types";

export interface StoreState {
  comment: string;
  status: "idle" | "loading" | "done" | "error";
  result: Verdict | null;
  source: "live" | "mock" | null;
  model: string | null;
  error: string | null;
}

let state: StoreState = {
  comment: "",
  status: "idle",
  result: null,
  source: null,
  model: null,
  error: null,
};

const subs = new Set<() => void>();
const emit = () => subs.forEach((fn) => fn());

export const store = {
  get: () => state,
  subscribe(fn: () => void) {
    subs.add(fn);
    return () => {
      subs.delete(fn);
    };
  },
  setComment(text: string) {
    state = { ...state, comment: text };
    emit();
  },
  reset() {
    state = { ...state, status: "idle", result: null, source: null, model: null, error: null };
    emit();
  },
  async submit(text?: string) {
    const comment = text != null ? text : state.comment;
    state = { ...state, comment, status: "loading", error: null };
    emit();
    try {
      const { result, source, model } = await moderate(comment);
      state = { ...state, status: "done", result, source, model, error: null };
    } catch (e) {
      const message =
        e instanceof EmptyCommentError
          ? e.message
          : e instanceof Error && e.message
            ? e.message
            : "Something went wrong.";
      state = { ...state, status: "error", result: null, error: message };
    }
    emit();
  },
};

/** Subscribe a component to the shared store. */
export function useStore(): StoreState {
  return useSyncExternalStore(store.subscribe, store.get, store.get);
}
