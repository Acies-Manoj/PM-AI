import { useState, type ReactNode } from "react";
import { IconChevronRight } from "./icons";
import "./Collapsible.css";

interface CollapsibleProps {
  /** Words after "View" / "Hide", e.g. "analysis plan". */
  label: string;
  children: ReactNode;
  defaultOpen?: boolean;
}

/** A closed-by-default section opened with a "View …" button, the same pattern as
 * "View agent generated code" on the Analysis page. */
export default function Collapsible({ label, children, defaultOpen = false }: CollapsibleProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="collapsible">
      <button type="button" className="collapsible__toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className={`collapsible__arrow${open ? " collapsible__arrow--open" : ""}`}>
          <IconChevronRight />
        </span>
        {open ? `Hide ${label}` : `View ${label}`}
      </button>
      {open && <div className="collapsible__body">{children}</div>}
    </div>
  );
}
