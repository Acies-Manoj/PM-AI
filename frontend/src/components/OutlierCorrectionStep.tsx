import ThinkingLoader from "./ThinkingLoader";
import { LOADING } from "../utils/loadingMessages";
import { useEffect, useRef, useState } from "react";
import type { OutliersResponse } from "../api/audit";
import { downloadFlaggedOutliersUrl, fetchOutliers } from "../api/audit";
import SegmentOutlierTab from "./SegmentOutlierTab";
import TemperatureOutlierTab from "./TemperatureOutlierTab";
import FileUploadCard from "./FileUploadCard";
import StatTile from "./StatTile";
import { IconDoc, IconGrid, IconClock, IconSnowflake, IconDownload } from "./icons";
import "./OutlierCorrectionStep.css";

interface OutlierCorrectionStepProps {
  sessionId: string;
  onFileCorrected: (file: File) => void | Promise<unknown>;
  onProceed: () => void;
  uploading: boolean;
  uploadError: string | null;
}

const REUPLOAD_SLOT_CONFIG = {
  id: "sensiwatch" as const,
  title: "Corrected SensiWatch export",
  description: "The same trips, corrected in SensiWatch, then re-exported.",
  required: false,
  accept: ".xlsx,.xls,.csv",
  acceptLabel: "Excel or CSV (.xlsx, .xls, .csv)",
};

type OutlierSubTab = "segment" | "temperature" | "others";

export default function OutlierCorrectionStep({
  sessionId,
  onFileCorrected,
  onProceed,
  uploading,
  uploadError,
}: OutlierCorrectionStepProps) {
  const [data, setData] = useState<OutliersResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [subTab, setSubTab] = useState<OutlierSubTab>("segment");
  const proceededRef = useRef(false);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchOutliers(sessionId)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    proceededRef.current = false;
    setData(null);
    setSelectedFile(null);
    setSubTab("segment");
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const flaggedCount = data
    ? data.segment.flagged_trips + data.temperature.too_warm_count + data.temperature.too_cold_count
    : null;

  useEffect(() => {
    if (flaggedCount === 0 && !proceededRef.current) {
      proceededRef.current = true;
      onProceed();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flaggedCount]);

  if (loading) {
    return <ThinkingLoader messages={LOADING.outliers} />;
  }
  if (error) {
    return (
      <div className="outlier-tab__error">
        Could not load outlier data: {error}
        <button type="button" className="outlier-tab__retry" onClick={load}>Retry</button>
      </div>
    );
  }
  if (!data || flaggedCount === 0) {
    // Zero flagged: onProceed() above is already advancing past this step.
    return <p className="outlier-tab__loading">No outliers flagged. Continuing…</p>;
  }

  const segmentFlagged = data.segment.flagged_trips;
  const tempBreaches = data.temperature.too_warm_count + data.temperature.too_cold_count;
  const totalTrips = data.segment.total_trips || data.temperature.total_trips;
  const columnCount = data.segment.columns.length;

  return (
    <div className="outlier-step">
      <div className="outlier-step__overview">
        <StatTile icon={<IconDoc />} color="blue" value={totalTrips.toLocaleString()} label="Trips Uploaded" />
        <StatTile icon={<IconGrid />} color="teal" value={columnCount} label="Columns" />
        <StatTile icon={<IconClock />} color={segmentFlagged > 0 ? "amber" : "purple"} value={segmentFlagged} label="Segment Outliers" />
        <StatTile icon={<IconSnowflake />} color={tempBreaches > 0 ? "error" : "purple"} value={tempBreaches} label="Temp Breaches" />
      </div>

      <p className="outlier-step__intro">
        <strong>{flaggedCount}</strong> trip(s) were flagged for unusual duration or temperature.
        Download them, correct the underlying readings in SensiWatch, and re-upload the export,
        or continue without correcting them.
      </p>

      <div className="outlier-step__subtabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={subTab === "segment"}
          className={`outlier-step__subtab ${subTab === "segment" ? "outlier-step__subtab--active" : ""}`}
          onClick={() => setSubTab("segment")}
        >
          Segment Days
          <span className="outlier-step__subtab-count">{segmentFlagged}</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={subTab === "temperature"}
          className={`outlier-step__subtab ${subTab === "temperature" ? "outlier-step__subtab--active" : ""}`}
          onClick={() => setSubTab("temperature")}
        >
          Mean Temp
          <span className="outlier-step__subtab-count">{tempBreaches}</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={subTab === "others"}
          className={`outlier-step__subtab ${subTab === "others" ? "outlier-step__subtab--active" : ""}`}
          onClick={() => setSubTab("others")}
        >
          Others
        </button>
      </div>

      <div className="outlier-step__section">
        {subTab === "segment" ? (
          <SegmentOutlierTab data={data.segment} sessionId={sessionId} onUpdated={setData} />
        ) : subTab === "temperature" ? (
          <TemperatureOutlierTab data={data.temperature} sessionId={sessionId} onUpdated={setData} />
        ) : (
          <p className="outlier-step__empty-subtab">No other outliers found.</p>
        )}
      </div>

      <div className="outlier-step__resolve">
        <div className="outlier-step__resolve-card">
          <div className="outlier-step__resolve-header">
            <div className="outlier-step__resolve-header-text">
              <h3 className="outlier-step__option-title">Corrected SensiWatch export</h3>
              <p className="outlier-step__option-desc">
                Download the flagged trips, correct the underlying readings in SensiWatch, then re-upload the export.
              </p>
            </div>
            <div className="outlier-step__resolve-actions">
              <a className="outlier-step__download" href={downloadFlaggedOutliersUrl(sessionId)} download>
                <IconDownload />
                Download flagged data
              </a>
              <button
                type="button"
                className="btn btn--primary outlier-step__btn"
                disabled={!selectedFile || uploading}
                onClick={() => selectedFile && onFileCorrected(selectedFile)}
              >
                {uploading ? "Uploading…" : "Upload corrected file"}
              </button>
            </div>
          </div>

          <FileUploadCard
            config={REUPLOAD_SLOT_CONFIG}
            file={selectedFile}
            error={uploadError ?? undefined}
            onSelect={setSelectedFile}
            onRemove={() => setSelectedFile(null)}
            hideHeader
            compact
          />
        </div>

        <div className="outlier-step__skip-row">
          <span className="outlier-step__skip-hint">
            Skipping keeps flagged trips unedited. You can still correct and re-upload later.
          </span>
          <button type="button" className="outlier-step__skip-link" onClick={onProceed}>
            Skip correction, continue to Standard Checks →
          </button>
        </div>
      </div>
    </div>
  );
}
