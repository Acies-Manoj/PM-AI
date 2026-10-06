import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { explanationLines } from "../utils/slideText";
import "./SlidePreview.css";

/** An on-screen replica of one slide of the exported .pptx (see backend
 * report_generator.ReportBuilder): the same 16:9 box, title, logo corner, one/two-line
 * explanation, full-width chart, caption and Carrier footer, in the same positions.
 * Everything is sized in container-width units (`cqw`), so the preview keeps its
 * proportions at any width -- big in the stage, tiny in a thumbnail. */

const LOGO_SRC = "/carrier-logo.svg";
const COVER_ART_SRC = "/cover/cover-art.jpg";

// Same break points the exporter uses, so the preview wraps like the real slide.
function titleSize(heading: string): string {
  if (heading.length <= 50) return "title--xl";
  if (heading.length <= 70) return "title--lg";
  if (heading.length <= 100) return "title--md";
  return "title--sm";
}

function Footer() {
  return (
    <>
      <span className="slide-preview__footer slide-preview__footer--left">
        © {new Date().getFullYear()} Carrier. All Rights Reserved.
      </span>
      <span className="slide-preview__footer slide-preview__footer--right">A Carrier Company</span>
    </>
  );
}

function Frame({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="slide-preview" role="img" aria-label={label}>
      {children}
      <Footer />
    </div>
  );
}

// 1in on the 13.333in-wide slide = 7.5cqw. Mirrors the exporter: the explanation keeps its font size and the chart
// area starts below however many lines it takes (backend ReportBuilder._explanation / _body_box).
const IN = 7.5;
function contentLayout(explanation: string | null | undefined) {
  const lines = explanation ? explanationLines(explanation) : 0;
  const explainH = Math.max(0.75, 0.31 * lines) * IN;
  const bodyTop = explanation ? Math.max(2.0 * IN, 1.12 * IN + explainH + 0.13 * IN) : 2.0 * IN;
  return { explainH, bodyTop, bodyH: 6.5 * IN - bodyTop };
}

interface ContentSlideProps {
  heading: string;
  /** The one/two-line explanation under the title (see utils/slideText.ts). */
  explanation?: string | null;
  /** Small grey note under the chart -- a drill-down's filter line. */
  caption?: string | null;
  /** The chart (or table) drawn full width. */
  children: ReactNode;
}

/** A chart slide: title + logo, explanation, chart, caption. */
export function ContentSlidePreview({ heading, explanation, caption, children }: ContentSlideProps) {
  const box = contentLayout(explanation);
  return (
    <Frame label={heading}>
      <h4 className={`slide-preview__title slide-preview__${titleSize(heading)}`}>{heading}</h4>
      <img className="slide-preview__logo" src={LOGO_SRC} alt="Carrier" />
      {explanation && (
        <p className="slide-preview__explanation" style={{ height: `${box.explainH}cqw` }}>
          {explanation}
        </p>
      )}
      <div className="slide-preview__body" style={{ top: `${box.bodyTop}cqw`, height: `${box.bodyH}cqw` }}>
        {children}
      </div>
      {caption && <p className="slide-preview__caption">{caption}</p>}
    </Frame>
  );
}

/** The cover: the Carrier template's photo-grid cover, with the title and subtitle on top. The
 * artwork is a picture of that layout (logo, photos, colour blocks); only the text is live. */
export function CoverSlidePreview({ title, subtitle, detail }: { title: string; subtitle?: string | null; detail?: string | null }) {
  return (
    <div className="slide-preview" role="img" aria-label="Cover slide">
      <img className="slide-preview__cover-art" src={COVER_ART_SRC} alt="" />
      <h4 className="slide-preview__cover-title">{title}</h4>
      <p className="slide-preview__cover-sub">
        {subtitle}
        {detail && (
          <>
            <br />
            {detail}
          </>
        )}
      </p>
    </div>
  );
}

/** The closing summary slide: heading plus bullet points. */
export function SummarySlidePreview({ bullets }: { bullets: string[] }) {
  const longest = bullets.reduce((m, b) => Math.max(m, b.length), 0);
  const size = longest < 200 && bullets.length <= 4 ? "bullets--lg" : longest < 320 ? "bullets--md" : "bullets--sm";
  return (
    <Frame label="Summary slide">
      <h4 className="slide-preview__title slide-preview__title--xl">Summary</h4>
      <img className="slide-preview__logo" src={LOGO_SRC} alt="Carrier" />
      <ul className={`slide-preview__bullets slide-preview__${size}`}>
        {bullets.map((b, i) => (
          <li key={i}>{b}</li>
        ))}
      </ul>
    </Frame>
  );
}

const THUMB_BASE_WIDTH = 1000;

/** Draws its children at a fixed 1000px width and shrinks the whole picture to fit the box it sits in,
 * so a thumbnail is a true miniature of the slide (chart text included) rather than a re-layout. */
export function ThumbScaler({ children }: { children: ReactNode }) {
  const outer = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.2);
  useLayoutEffect(() => {
    const el = outer.current;
    if (!el) return;
    const update = () => setScale(el.clientWidth / THUMB_BASE_WIDTH);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return (
    <div ref={outer} className="thumb-scaler">
      <div className="thumb-scaler__inner" style={{ transform: `scale(${scale})` }}>
        {children}
      </div>
    </div>
  );
}
