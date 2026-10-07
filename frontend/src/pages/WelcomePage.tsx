import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import {
  IconUpload,
  IconShieldSearch,
  IconSparkle,
  IconGrid,
  IconClipboard,
  IconLayers,
  IconChevronRight,
  IconSnowflake,
  IconShieldCheck,
  IconZap,
  IconDownload,
} from "../components/icons";
import "./WelcomePage.css";

const STEPS = [
  {
    step: 1,
    title: "Upload",
    icon: <IconUpload />,
    color: "blue",
    description: "Provide your SensiWatch/ColdStream export, a client brief, and any KPI or analysis definition profiles.",
  },
  {
    step: 2,
    title: "Planner",
    icon: <IconLayers />,
    color: "amber",
    description: "The AI Planner reads your brief and your data's column details, then suggests features and analyses. Accept or reject each one.",
  },
  {
    step: 3,
    title: "Audit",
    icon: <IconShieldSearch />,
    color: "teal",
    description: "Flags duplicates, empty columns, and Segment Length and Temperature outliers, with inline fixes before you trust the numbers.",
  },
  {
    step: 4,
    title: "Features",
    icon: <IconSparkle />,
    color: "purple",
    description: "Compute KPIs from your Customer KPI Profile, or build the planned features with the AI agent using your data's own columns.",
  },
  {
    step: 5,
    title: "Analysis",
    icon: <IconGrid />,
    color: "amber",
    description: "Run the planned analyses with interactive slicers, tables or charts, and drill down with the AI agent.",
  },
  {
    step: 6,
    title: "Report",
    icon: <IconClipboard />,
    color: "blue",
    description: "Download a PowerPoint report with native, editable charts and insights, ready for sharing and decision-making.",
  },
] as const;

const BENEFITS = [
  { title: "Trusted & Audited Data", description: "Deterministic audits and outlier checks ensure clean, reliable data.", icon: <IconShieldCheck />, color: "blue" },
  { title: "Faster Decisions", description: "Go from raw exports to actionable insights in minutes.", icon: <IconZap />, color: "teal" },
  { title: "Interactive Analysis", description: "Drill down, slice, and explore what matters most.", icon: <IconGrid />, color: "purple" },
  { title: "Share with Confidence", description: "Export polished reports that drive action.", icon: <IconDownload />, color: "blue" },
] as const;

// Purely decorative -- a stylised refrigerated truck on a road with three
// small connected icon bubbles, not tied to any real shipment. Stands in for
// the reference mockup's illustration using the app's own icon style
// (stroke-based, currentColor) instead of a fabricated stock photo.
function TruckIllustration() {
  return (
    <svg className="welcome-page__illustration" viewBox="0 0 220 190" fill="none" aria-hidden="true">
      <path d="M10 150h200" stroke="var(--color-border)" strokeWidth="2" strokeLinecap="round" />
      <path d="M45 120 65 70 90 120Z" fill="var(--carrier-blue-tint-2)" />
      <path d="M75 120 100 55 130 120Z" fill="var(--carrier-blue-tint)" />
      <path d="M20 149c30-14 60-18 90-4 26 12 56 10 88-6" stroke="var(--carrier-blue-tint-2)" strokeWidth="3" strokeLinecap="round" fill="none" />
      <rect x="14" y="112" width="10" height="16" rx="2" fill="var(--accent-teal-bg)" />
      <path d="M19 112v-14" stroke="var(--accent-teal)" strokeWidth="2" strokeLinecap="round" />
      <path d="M19 104c-6-2-8-8-6-13 5 1 9 6 9 13Z" fill="var(--accent-teal)" />
      <g transform="translate(60,95)">
        <rect x="0" y="0" width="72" height="34" rx="4" fill="#fff" stroke="var(--carrier-blue)" strokeWidth="2" />
        <path d="M0 34V10a4 4 0 0 1 4-4h20v28Z" fill="var(--carrier-blue-tint)" stroke="var(--carrier-blue)" strokeWidth="2" strokeLinejoin="round" />
        <path d="M72 34V16h14l8 8v10Z" fill="var(--carrier-light-blue)" stroke="var(--carrier-blue)" strokeWidth="2" strokeLinejoin="round" />
        <circle cx="80" cy="19" r="2" fill="#fff" />
        <g stroke="var(--carrier-blue)" strokeWidth="1.4" strokeLinecap="round">
          <path d="M12 16v8M8 20h8" />
        </g>
        <circle cx="18" cy="38" r="7" fill="var(--color-text)" />
        <circle cx="18" cy="38" r="3" fill="#fff" />
        <circle cx="84" cy="38" r="7" fill="var(--color-text)" />
        <circle cx="84" cy="38" r="3" fill="#fff" />
      </g>

      {/* Dotted connectors + floating icon bubbles, echoing the reference's
          document/chart/document trio near the truck's cab. */}
      <path d="M132 100c14-6 22-16 26-28" stroke="var(--color-border)" strokeWidth="2" strokeDasharray="3 4" strokeLinecap="round" fill="none" />
      <path d="M168 60c6 10 6 20 2 30" stroke="var(--color-border)" strokeWidth="2" strokeDasharray="3 4" strokeLinecap="round" fill="none" />
      <path d="M170 92c4 8 4 16 0 24" stroke="var(--color-border)" strokeWidth="2" strokeDasharray="3 4" strokeLinecap="round" fill="none" />

      <g transform="translate(146,52)">
        <circle r="16" fill="var(--color-success-bg)" />
        <path d="M-6 -7h9l4 4v10H-6Z" stroke="var(--color-success)" strokeWidth="1.5" strokeLinejoin="round" />
        <path d="M3 -7v4h4" stroke="var(--color-success)" strokeWidth="1.5" strokeLinejoin="round" />
      </g>
      <g transform="translate(184,84)">
        <circle r="16" fill="var(--carrier-blue-tint)" />
        <path d="M-6 6V0M-1 6v-9M4 6V-3" stroke="var(--carrier-blue)" strokeWidth="1.8" strokeLinecap="round" />
      </g>
      <g transform="translate(184,124)">
        <circle r="16" fill="var(--accent-purple-bg)" />
        <path d="M-6 -7h9l4 4v10H-6Z" stroke="var(--accent-purple)" strokeWidth="1.5" strokeLinejoin="round" />
        <path d="M3 -7v4h4" stroke="var(--accent-purple)" strokeWidth="1.5" strokeLinejoin="round" />
      </g>
    </svg>
  );
}

export default function WelcomePage() {
  const navigate = useNavigate();

  return (
    <div className="welcome-page">
      <Header subtitle="Welcome" />
      <main className="welcome-page__main">
        <div className="welcome-page__card">
          <div className="welcome-page__hero-row">
            <TruckIllustration />

            <section className="welcome-page__hero">
              <span className="welcome-page__badge">
                <IconSnowflake /> Cold-Chain / Post-Harvest
              </span>
              <h1 className="welcome-page__title">Program Manager AI</h1>
              <span className="welcome-page__title-underline" aria-hidden="true" />
              <p className="welcome-page__lede">
                A smart program management tool that turns messy shipment data into a clear plan, clean audited datasets,
                engineered KPIs, interactive analysis, and a downloadable report.
              </p>
              <button type="button" className="btn btn--primary welcome-page__cta" onClick={() => navigate("/upload")}>
                Get Started <IconChevronRight />
              </button>
            </section>
          </div>

          <section className="welcome-page__flow">
            <h2 className="welcome-page__flow-title">
              <span className="welcome-page__flow-diamond" aria-hidden="true" /> How it works{" "}
              <span className="welcome-page__flow-diamond" aria-hidden="true" />
            </h2>
            <div className="welcome-page__steps">
              {STEPS.map((s, idx) => (
                <div className="welcome-page__step" key={s.step}>
                  <div className="welcome-page__step-top">
                    <span className={`welcome-page__step-icon welcome-page__step-icon--${s.color}`}>{s.icon}</span>
                    <span className={`welcome-page__step-number welcome-page__step-number--${s.color}`}>Step {s.step}</span>
                  </div>
                  <h3 className="welcome-page__step-title">{s.title}</h3>
                  <p className="welcome-page__step-description">{s.description}</p>
                  <span className={`welcome-page__step-underline welcome-page__step-underline--${s.color}`} aria-hidden="true" />
                  {idx < STEPS.length - 1 && (
                    <span className="welcome-page__step-connector" aria-hidden="true">
                      <IconChevronRight />
                    </span>
                  )}
                </div>
              ))}
            </div>
          </section>

          <section className="welcome-page__benefits">
            {BENEFITS.map((b) => (
              <div className="welcome-page__benefit" key={b.title}>
                <span className={`welcome-page__benefit-icon welcome-page__benefit-icon--${b.color}`}>{b.icon}</span>
                <div>
                  <h3 className="welcome-page__benefit-title">{b.title}</h3>
                  <p className="welcome-page__benefit-description">{b.description}</p>
                </div>
              </div>
            ))}
          </section>
        </div>
      </main>
    </div>
  );
}
