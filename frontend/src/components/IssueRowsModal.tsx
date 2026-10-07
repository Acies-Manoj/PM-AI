import ThinkingLoader from "./ThinkingLoader";
import { LOADING } from "../utils/loadingMessages";
import { useEffect, useState } from "react";
import { fetchIssueRows, AuditApiError } from "../api/audit";
import ExcelTable from "./ExcelTable";
import "./IssueRowsModal.css";

interface IssueRowsModalProps {
  title: string;
  sessionId: string;
  issueId: string;
  onClose: () => void;
}


export default function IssueRowsModal({ title, sessionId, issueId, onClose }: IssueRowsModalProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<{ columns: string[]; rows: Record<string, unknown>[]; total: number } | null>(
    null
  );

  useEffect(() => {
    let cancelled = false;
    fetchIssueRows(sessionId, issueId)
      .then((res) => {
        if (cancelled) return;
        setData({ columns: res.columns, rows: res.rows, total: res.total_matching });
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof AuditApiError ? err.message : "Could not load the affected rows.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, issueId]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="issue-rows-modal__backdrop" onClick={onClose}>
      <div className="issue-rows-modal" onClick={(e) => e.stopPropagation()}>
        <div className="issue-rows-modal__head">
          <div>
            <h3 className="issue-rows-modal__title">{title}</h3>
            {data && (
              <p className="issue-rows-modal__subtitle">
                Showing {data.rows.length.toLocaleString()} of {data.total.toLocaleString()} affected row(s), all{" "}
                {data.columns.length} columns
              </p>
            )}
          </div>
          <button type="button" className="issue-rows-modal__close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {loading && <ThinkingLoader variant="inline" messages={LOADING.rows} />}
        {error && <div className="issue-rows-modal__status issue-rows-modal__status--error">{error}</div>}

        {data && (
          <div className="issue-rows-modal__scroll">
            <ExcelTable columns={data.columns} rows={data.rows} />
          </div>
        )}
      </div>
    </div>
  );
}
