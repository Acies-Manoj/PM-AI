import { useCallback, useRef, useSyncExternalStore, type Dispatch, type SetStateAction } from "react";

// A tiny in-memory store that outlives page components. Every wizard page
// (Audit, Features, Analysis, Report) used to keep its data in page-local
// useState, so leaving a page and coming back threw it all away: computed
// features were recomputed, selections and slide order reset, and the Audit
// page even re-ran the audit over the PM's resolved decisions.
//
// Values live here instead, keyed by string. Setters write to the store
// directly (not through a mounted component), so a request that finishes
// after the PM navigated away still lands its result.
//
// The store is intentionally NOT persisted to storage: the uploaded files are
// File objects that can't survive a reload, so a reload restarts the flow.

const values = new Map<string, unknown>();
const refs = new Map<string, unknown>();
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function notify() {
  listeners.forEach((l) => l());
}

/** Drop-in for useState whose value survives the component unmounting. */
export function useStoredState<T>(key: string, initial: T): [T, Dispatch<SetStateAction<T>>] {
  // Held in a ref so an inline `{}` default stays referentially stable --
  // useSyncExternalStore requires a stable snapshot between store changes.
  const initialRef = useRef(initial);
  const value = useSyncExternalStore(
    subscribe,
    () => (values.has(key) ? (values.get(key) as T) : initialRef.current)
  );

  const setValue = useCallback<Dispatch<SetStateAction<T>>>(
    (update) => {
      const prev = (values.has(key) ? values.get(key) : initialRef.current) as T;
      const next = typeof update === "function" ? (update as (p: T) => T)(prev) : update;
      if (Object.is(prev, next)) return;
      values.set(key, next);
      notify();
    },
    [key]
  );

  return [value, setValue];
}

/** Drop-in for a mutable useRef whose object survives unmounting (no re-render on change). */
export function useStoredRef<T>(key: string, create: () => T): T {
  if (!refs.has(key)) refs.set(key, create());
  return refs.get(key) as T;
}

// Keys are namespaced "<stage>.<name>". The audit stage owns "audit.*";
// everything after it derives from the audited data.
const DOWNSTREAM_PREFIXES = ["features.", "analysis.", "report."];

function clearWhere(match: (key: string) => boolean) {
  for (const key of [...values.keys()]) if (match(key)) values.delete(key);
  for (const key of [...refs.keys()]) if (match(key)) refs.delete(key);
  notify();
}

/** The audited data changed (a decision was applied or reverted): features, analyses and the report must be rebuilt. */
export function resetDownstreamState() {
  clearWhere((key) => DOWNSTREAM_PREFIXES.some((p) => key.startsWith(p)));
}

/** A different file/session is in play: forget everything. */
export function resetAllState() {
  clearWhere(() => true);
}
