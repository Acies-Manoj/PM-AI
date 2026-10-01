import { useEffect, useState } from "react";
import { IconSparkle } from "./icons";
import "./ThinkingLoader.css";

interface ThinkingLoaderProps {
  /** Phrases shown one after another while the work runs, in the order it really happens
   * ("Reading…", "Analyzing…", "Calculating…"). The last one stays until the work finishes. */
  messages: readonly string[];
  /** "block" is a panel for page- or section-level waits; "inline" is a single line for cards and status rows. */
  variant?: "block" | "inline";
  /** A line under the phrase saying what to expect. */
  hint?: string;
  intervalMs?: number;
  /** Show a running "12s" counter, for slow tasks. */
  showElapsed?: boolean;
}

/** A small spinner for buttons and chips. */
export function Spinner({ size = 14 }: { size?: number }) {
  return <span className="thinking__spinner" style={{ width: size, height: size }} aria-hidden="true" />;
}

function useRotating(count: number, intervalMs: number): number {
  const [index, setIndex] = useState(0);
  useEffect(() => {
    if (count < 2) return;
    const timer = window.setInterval(() => setIndex((i) => Math.min(i + 1, count - 1)), intervalMs);
    return () => window.clearInterval(timer);
  }, [count, intervalMs]);
  return Math.min(index, Math.max(count - 1, 0));
}

function useElapsed(enabled: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    const started = Date.now();
    const timer = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [enabled]);
  return seconds;
}

/** Friendly, animated waiting state: a pulsing mark, a phrase that moves through what is
 * happening, and a soft progress shimmer. Announced politely to screen readers. */
export default function ThinkingLoader({ messages, variant = "block", hint, intervalMs = 2600, showElapsed = false }: ThinkingLoaderProps) {
  const index = useRotating(messages.length, intervalMs);
  const seconds = useElapsed(showElapsed);
  const phrase = messages[index] ?? "Working…";

  if (variant === "inline") {
    return (
      <span className="thinking thinking--inline" role="status" aria-live="polite">
        <Spinner />
        <span key={phrase} className="thinking__phrase">
          {phrase}
        </span>
        <span className="thinking__dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        {showElapsed && seconds >= 5 && <span className="thinking__elapsed">{seconds}s</span>}
      </span>
    );
  }

  return (
    <div className="thinking thinking--block" role="status" aria-live="polite">
      <div className="thinking__orb" aria-hidden="true">
        <span className="thinking__ring" />
        <span className="thinking__ring thinking__ring--late" />
        <span className="thinking__core">
          <IconSparkle />
        </span>
      </div>
      <div className="thinking__body">
        <p className="thinking__line">
          <span key={phrase} className="thinking__phrase">
            {phrase}
          </span>
          <span className="thinking__dots" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          {showElapsed && seconds >= 5 && <span className="thinking__elapsed">{seconds}s</span>}
        </p>
        {hint && <p className="thinking__hint">{hint}</p>}
        <span className="thinking__bar" aria-hidden="true" />
      </div>
    </div>
  );
}
