import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Modal from "./Modal";
import AnalysisChart from "./AnalysisChart";
import { ContentSlidePreview, CoverSlidePreview, SummarySlidePreview, ThumbScaler } from "./SlidePreview";
import { IconPlus, IconRedo, IconTrash, IconUndo } from "./icons";
import type { AnalysisRepositoryEntry, EntryTranslation } from "../api/audit";
import { buildReportTree, drilldownSubtitle } from "../utils/reportTree";
import { EXPLAIN_MAX_LINES, explanationLines, shortExplanation } from "../utils/slideText";
import { moveSibling, type DeckState, type SlideEdit } from "../utils/deck";
import "./ReportEditorModal.css";

interface ReportEditorModalProps {
  /** Every finished analysis for this source (ticked or not). */
  entries: AnalysisRepositoryEntry[];
  staleIds: Set<string>;
  translations?: Record<string, EntryTranslation>;
  deck: DeckState;
  coverDefaults: { title: string; subtitle: string };
  summaryLoading: boolean;
  summaryError?: string;
  onChange: (next: DeckState) => void;
  onRegenerateSummary: () => void;
  onClose: () => void;
}

type Page =
  | { key: string; kind: "cover" }
  | { key: string; kind: "summary" }
  // `number` is null while the slide is unticked: it is not in the report, so it has no slide number.
  | { key: string; kind: "entry"; entry: AnalysisRepositoryEntry; number: string | null; parentId: string | null };

const HISTORY_LIMIT = 100;
// Keystrokes in the same field within this window undo as one step.
const TYPING_GROUP_MS = 1200;

const isTypingTarget = (t: EventTarget | null) => {
  const el = t as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
};

function Field({ label, hint, onReset, children }: { label: string; hint?: ReactNode; onReset?: () => void; children: ReactNode }) {
  return (
    <div className="report-editor__field">
      <div className="report-editor__field-head">
        <span className="report-editor__label">{label}</span>
        {onReset && (
          <button type="button" className="report-editor__reset" onClick={onReset}>
            Reset
          </button>
        )}
      </div>
      {children}
      {hint && <p className="report-editor__hint">{hint}</p>}
    </div>
  );
}

/** Edit the deck the way it will export: slide rail on the left (drag to reorder, delete, restore), the open
 * slide in the middle, its text fields on the right. Every change is undoable (Ctrl/Cmd+Z, Shift+Z to redo).
 * The deck itself lives with the page -- this component only proposes the next state through `onChange`. */
export default function ReportEditorModal({
  entries,
  staleIds,
  translations,
  deck,
  coverDefaults,
  summaryLoading,
  summaryError,
  onChange,
  onRegenerateSummary,
  onClose,
}: ReportEditorModalProps) {
  // Every slide the PM could include (stale ones can't be), in their order; ticked ones are numbered.
  const all = useMemo(() => buildReportTree(entries.filter((e) => !staleIds.has(e.id)), deck.order), [entries, staleIds, deck.order]);
  const includedTree = useMemo(
    () => buildReportTree(entries.filter((e) => deck.selected[e.id] && !staleIds.has(e.id)), deck.order),
    [entries, deck.selected, deck.order, staleIds]
  );
  const numbers = useMemo(() => new Map(includedTree.map((n) => [n.entry.id, n.number])), [includedTree]);
  const parentOf = useMemo(() => new Map(all.map((n) => [n.entry.id, n.parentId])), [all]);
  const pages: Page[] = useMemo(
    () => [
      { key: "cover", kind: "cover" },
      ...all.map((n): Page => ({ key: n.entry.id, kind: "entry", entry: n.entry, number: numbers.get(n.entry.id) ?? null, parentId: n.parentId })),
      { key: "summary", kind: "summary" },
    ],
    [all, numbers]
  );
  // Position in the exported deck: cover is 1, then each ticked slide, then the summary.
  const deckPosition = (key: string): number | null => {
    if (key === "cover") return 1;
    if (key === "summary") return includedTree.length + 2;
    const at = includedTree.findIndex((n) => n.entry.id === key);
    return at === -1 ? null : at + 2;
  };

  const [activeKey, setActiveKey] = useState("cover");
  const activeIdx = Math.max(0, pages.findIndex((p) => p.key === activeKey));
  const active = pages[activeIdx];
  // If the open slide disappears (the data changed underneath), land on a neighbour instead of a blank stage.
  useEffect(() => {
    if (!pages.some((p) => p.key === activeKey)) setActiveKey(pages[Math.min(activeIdx, pages.length - 1)].key);
  }, [pages, activeKey, activeIdx]);

  // -- history ----------------------------------------------------------------------------------
  const past = useRef<DeckState[]>([]);
  const future = useRef<DeckState[]>([]);
  const lastGroup = useRef<{ key: string; at: number } | null>(null);
  const [, bump] = useState(0);

  const commit = (next: DeckState, group?: string) => {
    const now = Date.now();
    const joinsLast = !!group && lastGroup.current?.key === group && now - lastGroup.current.at < TYPING_GROUP_MS;
    if (!joinsLast) {
      past.current.push(deck);
      if (past.current.length > HISTORY_LIMIT) past.current.shift();
    }
    lastGroup.current = group ? { key: group, at: now } : null;
    future.current = [];
    onChange(next);
    bump((n) => n + 1);
  };

  // A generated summary can arrive while the editor is open; undoing must not wipe it. Only a summary the
  // PM typed is part of history.
  const restore = (snap: DeckState): DeckState =>
    snap.bulletsEdited ? snap : { ...snap, bullets: deck.bulletsEdited ? snap.bullets : deck.bullets };

  const undo = () => {
    const prev = past.current.pop();
    if (!prev) return;
    future.current.push(deck);
    lastGroup.current = null;
    onChange(restore(prev));
    bump((n) => n + 1);
  };
  const redo = () => {
    const next = future.current.pop();
    if (!next) return;
    past.current.push(deck);
    lastGroup.current = null;
    onChange(restore(next));
    bump((n) => n + 1);
  };

  // -- actions ----------------------------------------------------------------------------------
  const setSelected = (id: string, on: boolean) => commit({ ...deck, selected: { ...deck.selected, [id]: on } });
  const editOf = (id: string): SlideEdit => deck.edits[id] ?? {};
  const setEdit = (id: string, patch: SlideEdit, group: string) => {
    const merged: SlideEdit = { ...editOf(id), ...patch };
    (Object.keys(merged) as (keyof SlideEdit)[]).forEach((k) => merged[k] === undefined && delete merged[k]);
    const edits = { ...deck.edits };
    if (Object.keys(merged).length === 0) delete edits[id];
    else edits[id] = merged;
    commit({ ...deck, edits }, `${id}:${group}`);
  };

  // -- keyboard ---------------------------------------------------------------------------------
  const keys = useRef({ undo, redo, step: (_d: number) => {} });
  keys.current = {
    undo,
    redo,
    step: (d: number) => setActiveKey(pages[Math.max(0, Math.min(pages.length - 1, activeIdx + d))].key),
  };
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "z") {
        // Our undo covers the whole deck, text fields included, so it replaces the browser's own.
        e.preventDefault();
        if (e.shiftKey) keys.current.redo();
        else keys.current.undo();
      } else if (mod && e.key.toLowerCase() === "y") {
        e.preventDefault();
        keys.current.redo();
      } else if (!isTypingTarget(e.target)) {
        if (e.key === "ArrowDown" || e.key === "ArrowRight") {
          e.preventDefault();
          keys.current.step(1);
        } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
          e.preventDefault();
          keys.current.step(-1);
        }
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  // -- what each slide shows ----------------------------------------------------------------------
  const texts = (entry: AnalysisRepositoryEntry, number: string | null) => {
    const edit = editOf(entry.id);
    const translated = translations?.[entry.id];
    const defaultName = translated?.name ?? entry.name;
    const defaultExplanation = shortExplanation(translated?.interpretation ?? entry.interpretation ?? entry.description);
    const defaultCaption = entry.chain ? drilldownSubtitle(entry.chain) : "";
    const name = edit.heading || defaultName;
    return {
      defaultName,
      defaultExplanation,
      defaultCaption,
      heading: number ? `${number}  ${name}` : name,
      explanation: edit.explanation ?? defaultExplanation,
      caption: edit.caption ?? defaultCaption,
    };
  };

  const coverTitle = deck.cover.title ?? coverDefaults.title;
  const coverSubtitle = deck.cover.subtitle ?? coverDefaults.subtitle;

  const renderPage = (page: Page, thumbnail: boolean) => {
    if (page.kind === "cover") return <CoverSlidePreview title={coverTitle} subtitle={coverSubtitle} />;
    if (page.kind === "summary") {
      return deck.bullets && deck.bullets.length > 0 ? (
        <SummarySlidePreview bullets={deck.bullets} />
      ) : (
        <div className="report-editor__pending">
          {summaryError ?? (summaryLoading ? "Writing the summary…" : "No summary yet — add bullet points on the right.")}
        </div>
      );
    }
    const t = texts(page.entry, page.number);
    return (
      <ContentSlidePreview heading={t.heading} explanation={t.explanation} caption={t.caption || null}>
        <AnalysisChart
          chartSpec={page.entry.chart_spec}
          chartType={page.entry.chart_type}
          resultTable={page.entry.result_table}
          fill
          thumbnail={thumbnail}
        />
      </ContentSlidePreview>
    );
  };

  const pageName = (page: Page) =>
    page.kind === "cover" ? "Cover" : page.kind === "summary" ? "Summary" : texts(page.entry, page.number).heading;

  // -- drag to reorder ----------------------------------------------------------------------------
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [drop, setDrop] = useState<{ key: string; after: boolean } | null>(null);
  const canDropOn = (page: Page) =>
    !!dragKey && page.kind === "entry" && page.key !== dragKey && parentOf.get(dragKey) === page.parentId;
  const endDrag = () => {
    setDragKey(null);
    setDrop(null);
  };

  const canUndo = past.current.length > 0;
  const canRedo = future.current.length > 0;

  // -- inspector ----------------------------------------------------------------------------------
  const setBullets = (bullets: string[], group?: string) => commit({ ...deck, bullets, bulletsEdited: true }, group);

  let inspector: ReactNode;
  if (active.kind === "cover") {
    inspector = (
      <>
        <h4 className="report-editor__inspector-title">Cover</h4>
        <Field label="Title" onReset={deck.cover.title !== undefined ? () => commit({ ...deck, cover: { ...deck.cover, title: undefined } }) : undefined}>
          <input
            className="report-editor__input"
            value={coverTitle}
            maxLength={60}
            onChange={(e) => commit({ ...deck, cover: { ...deck.cover, title: e.target.value } }, "cover:title")}
          />
        </Field>
        <Field label="Subtitle" onReset={deck.cover.subtitle !== undefined ? () => commit({ ...deck, cover: { ...deck.cover, subtitle: undefined } }) : undefined}>
          <input
            className="report-editor__input"
            value={coverSubtitle}
            maxLength={80}
            onChange={(e) => commit({ ...deck, cover: { ...deck.cover, subtitle: e.target.value } }, "cover:subtitle")}
          />
        </Field>
        <p className="report-editor__hint">The data's date range is added under the subtitle when the report is exported.</p>
      </>
    );
  } else if (active.kind === "summary") {
    const bullets = deck.bullets ?? [];
    inspector = (
      <>
        <h4 className="report-editor__inspector-title">Summary</h4>
        <p className="report-editor__hint">
          {deck.bulletsEdited
            ? "You've edited this summary, so it no longer updates when slides change."
            : "Written from the slides in this report. It updates when you add, delete or reorder slides, until you edit it."}
        </p>
        <ul className="report-editor__bullets">
          {bullets.map((b, i) => (
            <li key={i}>
              <textarea
                className="report-editor__input report-editor__textarea"
                rows={3}
                value={b}
                aria-label={`Bullet ${i + 1}`}
                onChange={(e) => setBullets(bullets.map((x, j) => (j === i ? e.target.value : x)), `bullet:${i}`)}
              />
              <button
                type="button"
                className="report-editor__icon-btn"
                aria-label={`Delete bullet ${i + 1}`}
                onClick={() => setBullets(bullets.filter((_, j) => j !== i))}
              >
                <IconTrash />
              </button>
            </li>
          ))}
        </ul>
        <div className="report-editor__row">
          <button type="button" className="report-editor__btn" onClick={() => setBullets([...bullets, ""])}>
            <IconPlus /> Add bullet
          </button>
          <button type="button" className="report-editor__btn" disabled={summaryLoading} onClick={onRegenerateSummary}>
            {summaryLoading ? "Writing…" : "Regenerate"}
          </button>
        </div>
        {summaryError && <p className="report-editor__error">{summaryError}</p>}
      </>
    );
  } else {
    const t = texts(active.entry, active.number);
    const edit = editOf(active.key);
    const over = explanationLines(t.explanation) > EXPLAIN_MAX_LINES;
    inspector = (
      <>
        <h4 className="report-editor__inspector-title">{active.number ? `Slide ${active.number}` : "Not in report"}</h4>
        <label className="report-editor__include">
          <input type="checkbox" checked={!!deck.selected[active.key]} onChange={(e) => setSelected(active.key, e.target.checked)} />
          Include in report
        </label>
        <Field label="Title" onReset={edit.heading !== undefined ? () => setEdit(active.key, { heading: undefined }, "reset") : undefined}>
          <input
            className="report-editor__input"
            value={edit.heading ?? t.defaultName}
            maxLength={120}
            onChange={(e) => setEdit(active.key, { heading: e.target.value || undefined }, "heading")}
          />
        </Field>
        <Field
          label="Explanation"
          onReset={edit.explanation !== undefined ? () => setEdit(active.key, { explanation: undefined }, "reset") : undefined}
          hint={
            <span className={over ? "report-editor__hint--warn" : undefined}>
              {over
                ? `Longer than ${EXPLAIN_MAX_LINES} lines — the slide will cut the rest off.`
                : "The chart moves down to make room for longer text."}
            </span>
          }
        >
          <textarea
            className="report-editor__input report-editor__textarea"
            rows={4}
            value={t.explanation}
            onChange={(e) => setEdit(active.key, { explanation: e.target.value }, "explanation")}
          />
        </Field>
        <Field label="Note under the chart" onReset={edit.caption !== undefined ? () => setEdit(active.key, { caption: undefined }, "reset") : undefined}>
          <input
            className="report-editor__input"
            value={t.caption}
            maxLength={140}
            placeholder="Optional"
            onChange={(e) => setEdit(active.key, { caption: e.target.value }, "caption")}
          />
        </Field>
        <p className="report-editor__hint">The chart and its data come from the analysis and can't be edited here.</p>
      </>
    );
  }

  return (
    <Modal title="Edit report" onClose={onClose} panelClassName="report-editor__panel">
      <div className="report-editor__toolbar" role="toolbar" aria-label="Slide tools">
        <button type="button" className="report-editor__tool" onClick={undo} disabled={!canUndo} title="Undo (Ctrl+Z)">
          <IconUndo /> Undo
        </button>
        <button type="button" className="report-editor__tool" onClick={redo} disabled={!canRedo} title="Redo (Ctrl+Shift+Z)">
          <IconRedo /> Redo
        </button>
        <span className="report-editor__count">{includedTree.length + 2} slides in report</span>
      </div>

      <div className="report-editor">
        <nav className="report-editor__rail" aria-label="Slides">
          <ol className="report-editor__thumbs">
            {pages.map((page) => {
              const dropHere = drop?.key === page.key;
              return (
                <li
                  key={page.key}
                  className={[
                    "report-editor__thumb",
                    page.key === active.key ? "is-active" : "",
                    dragKey === page.key ? "is-dragging" : "",
                    page.kind === "entry" && page.number === null ? "is-off" : "",
                    dropHere ? (drop!.after ? "drop-after" : "drop-before") : "",
                  ].join(" ")}
                  draggable={page.kind === "entry"}
                  onDragStart={(e) => {
                    if (page.kind !== "entry") return;
                    e.dataTransfer.effectAllowed = "move";
                    e.dataTransfer.setData("text/plain", page.key); // Firefox won't start a drag without data
                    setDragKey(page.key);
                  }}
                  onDragOver={(e) => {
                    if (!canDropOn(page)) return;
                    e.preventDefault();
                    const rect = e.currentTarget.getBoundingClientRect();
                    const after = e.clientY > rect.top + rect.height / 2;
                    if (drop?.key !== page.key || drop.after !== after) setDrop({ key: page.key, after });
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    if (dragKey && drop && canDropOn(page)) {
                      commit({ ...deck, order: moveSibling(deck.order, parentOf, dragKey, page.key, drop.after) });
                    }
                    endDrag();
                  }}
                  onDragEnd={endDrag}
                >
                  <span className="report-editor__thumb-num">{deckPosition(page.key) ?? "–"}</span>
                  <button
                    type="button"
                    className="report-editor__thumb-art"
                    aria-current={page.key === active.key}
                    aria-label={`${pageName(page)}${page.kind === "entry" && page.number === null ? " (not in report)" : ""}`}
                    onClick={() => setActiveKey(page.key)}
                  >
                    <ThumbScaler>{renderPage(page, true)}</ThumbScaler>
                  </button>
                  {page.kind === "entry" ? (
                    <>
                      <input
                        type="checkbox"
                        className="report-editor__check"
                        checked={page.number !== null}
                        onChange={(e) => setSelected(page.key, e.target.checked)}
                        aria-label={`Include ${pageName(page)} in report`}
                      />
                    </>
                  ) : (
                    <input
                      type="checkbox"
                      className="report-editor__check"
                      checked
                      disabled
                      title="Always included"
                      aria-label={`${pageName(page)} is always included`}
                      readOnly
                    />
                  )}
                </li>
              );
            })}
          </ol>

        </nav>

        <section className="report-editor__stage" aria-label="Open slide">
          <div className="report-editor__slide" key={active.key}>
            {renderPage(active, false)}
          </div>
        </section>

        <aside className="report-editor__inspector" aria-label="Slide text">
          {inspector}
        </aside>
      </div>
    </Modal>
  );
}
