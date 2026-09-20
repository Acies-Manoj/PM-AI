import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import { IconChevronLeft, IconDoc } from "../components/icons";
import type { AuditReportsState, FilesState } from "../App";
import "./ReportPage.css";

interface ReportPageProps {
  files: FilesState;
  auditReports: AuditReportsState;
}

// The .pptx export used to be built entirely from the pivot-table Analysis
// system, which has been replaced by the Analysis Agent (see
// analysis_repository.py / AnalysisPage.tsx). Report generation hasn't been
// rewired to the new agent-produced analyses yet -- this page is a
// placeholder that keeps the route and the Analysis page's nav button
// working until that rewiring happens.
export default function ReportPage(_props: ReportPageProps) {
  const navigate = useNavigate();

  return (
    <div className="report-page">
      <Header subtitle="Report" />
      <main className="report-page__main">
        <StepIndicator current={6} />

        <PageHeader icon={<IconDoc />} title="Report" subtitle="Export a report from this session's analyses." />

        <div className="report-page__empty">
          <p>
            Report generation is being rebuilt to work with the new Analysis Agent's charts and
            interpretations -- check back soon.
          </p>
          <button type="button" className="report-page__btn report-page__btn--secondary" onClick={() => navigate("/analysis")}>
            <IconChevronLeft /> Back to Analysis
          </button>
        </div>
      </main>
    </div>
  );
}
