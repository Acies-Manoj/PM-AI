import { useEffect, useRef, type ReactNode } from "react";
import "./Modal.css";

interface ModalProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  headerExtra?: ReactNode;
  /** When this changes the body scrolls back to the top (e.g. the modal now shows a different item). */
  resetScrollKey?: string;
}

export default function Modal({ title, onClose, children, headerExtra, resetScrollKey }: ModalProps) {
  const bodyRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 });
  }, [resetScrollKey]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="modal__overlay" onClick={onClose}>
      <div className="modal__panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal__head">
          <h3 className="modal__title">{title}</h3>
          <div className="modal__head-right">
            {headerExtra}
            <button type="button" className="modal__close" onClick={onClose} aria-label="Close">
              ×
            </button>
          </div>
        </div>
        <div className="modal__body" ref={bodyRef}>
          {children}
        </div>
      </div>
    </div>
  );
}
