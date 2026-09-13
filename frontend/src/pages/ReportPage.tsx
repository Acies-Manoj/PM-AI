import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import { generateReport, reportDownloadUrl, ReportApiError } from "../api/report";
import type { ReportOutput } from "../api/report";
import type { FilesState } from "../App";
import "./ReportPage.css";

interface ReportPageProps {
  files: FilesState;
  analysisId: string | null;
}

export default function ReportPage({ files, analysisId }: ReportPageProps) {
  const navigate = useNavigate();
  const [report, setReport] = useState<ReportOutput | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fmt, setFmt] = useState<"html" | "markdown">("html");

  const handleGenerate = async () => {
    if (!analysisId) return;
    setLoading(true);
    setError(null);
    try {
      const r = await generateReport(analysisId, fmt);
      setReport(r);
    } catch (err) {
      setError(err instanceof ReportApiError ? err.message : "Report generation failed.");
    } finally {
      setLoading(false);
    }
  };

  if (!files.sensiwatch || !analysisId) {
    return (
      <div className="report-page">
        <Header />
        <main className="report-page__main">
          <StepIndicator current={6} />
          <div className="report-page__empty">
            <p>Complete the analysis step before generating a report.</p>
            <button type="button" className="report-page__btn report-page__btn--primary" onClick={() => navigate("/analysis")}>
              Go to Analysis
            </button>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="report-page">
      <Header />
      <main className="report-page__main">
        <StepIndicator current={6} />

        <div className="report-page__intro">
          <h1 className="report-page__heading">Report Generation</h1>
          <p className="report-page__lede">
            The Report Agent assembles all analysis steps, charts, and computed metrics into a
            final deliverable for the client.
          </p>
        </div>

        <div className="report-page__controls">
          <div className="report-page__fmt-row">
            <span className="report-page__fmt-label">Format:</span>
            {(["html", "markdown"] as const).map((f) => (
              <button
                key={f}
                type="button"
                className={`report-page__fmt-btn ${fmt === f ? "report-page__fmt-btn--active" : ""}`}
                onClick={() => setFmt(f)}
              >
                {f === "html" ? "HTML" : "Markdown"}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="report-page__btn report-page__btn--primary"
            onClick={handleGenerate}
            disabled={loading}
          >
            {loading ? "Generating…" : "Generate Report"}
          </button>
        </div>

        {error && <p className="report-page__error">{error}</p>}

        {report && (
          <>
            <div className="report-page__actions-bar">
              <span className="report-page__ready">Report ready</span>
              <a
                className="report-page__download-btn"
                href={reportDownloadUrl(analysisId, fmt)}
                download={`cold_chain_report.${fmt === "html" ? "html" : "md"}`}
              >
                Download {fmt === "html" ? "HTML" : "Markdown"}
              </a>
            </div>

            {fmt === "html" ? (
              <iframe
                className="report-page__preview"
                srcDoc={report.content}
                title="Report Preview"
                sandbox="allow-same-origin"
              />
            ) : (
              <pre className="report-page__markdown-preview">{report.content}</pre>
            )}
          </>
        )}

        <div className="report-page__nav">
          <button type="button" className="report-page__btn report-page__btn--secondary" onClick={() => navigate("/analysis")}>
            Back to Analysis
          </button>
        </div>
      </main>
    </div>
  );
}
