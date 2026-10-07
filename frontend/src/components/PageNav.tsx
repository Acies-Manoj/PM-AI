import type { ReactNode } from "react";
import { IconChevronLeft } from "./icons";

interface PageNavProps {
  position: "top" | "bottom";
  onBack: () => void;
  backDisabled?: boolean;
  /** The forward action(s), shown on the right (e.g. "Proceed to Audit"). */
  children?: ReactNode;
}

/** Back on the left, the forward action on the right. Used at the top and the bottom of a page. */
export default function PageNav({ position, onBack, backDisabled, children }: PageNavProps) {
  return (
    <div className={`page-nav page-nav--${position}`}>
      <button type="button" className="btn btn--secondary" onClick={onBack} disabled={backDisabled}>
        <IconChevronLeft /> Back
      </button>
      <div className="page-nav__next">{children}</div>
    </div>
  );
}
