import type { FeatureResult } from "../api/audit";
import { tidyText } from "../utils/tidyText";
import Modal from "./Modal";
import Collapsible from "./Collapsible";
import { Distribution, displayStats } from "./FeatureCard";
import "./FeatureCard.css";

interface FeatureDetailModalProps {
  feature: FeatureResult;
  onClose: () => void;
}

const STAT_NAMES: Record<string, string> = { mean: "Average", max: "Highest" };

/** What a feature is and how it came out, in the order a reader asks: what it means, how many rows have a
 * value, what the values look like, and (collapsed) how it was worked out and checked. */
export default function FeatureDetailModal({ feature, onClose }: FeatureDetailModalProps) {
  const distributionEntries = Object.entries(feature.distribution);
  const statsEntries = displayStats(feature.stats);
  const maxCount = distributionEntries.length > 0 ? Math.max(...distributionEntries.map(([, v]) => v)) : 0;

  return (
    <Modal title={feature.name} onClose={onClose}>
      <p className="feature-card__modal-description">{tidyText(feature.description)}</p>

      {statsEntries.length > 0 && (
        <section className="feature-card__section">
          <h4 className="feature-card__section-title">Typical values</h4>
          <div className="feature-card__stats feature-card__stats--modal">
            {statsEntries.map(([key, value]) => (
              <div className="feature-card__stat-tile" key={key}>
                <span className="feature-card__stat-value">{value}</span>
                <span className="feature-card__stat-label">{STAT_NAMES[key] ?? key}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {distributionEntries.length > 0 && (
        <section className="feature-card__section">
          <h4 className="feature-card__section-title">How many rows have each value</h4>
          <Distribution entries={distributionEntries} maxCount={maxCount} />
        </section>
      )}

      {(feature.validation_note || feature.generated_code) && (
        <section className="feature-card__section">
          <h4 className="feature-card__section-title">How it was worked out</h4>
          <div className="feature-card__how">
            {feature.validation_note && (
              <Collapsible label="validation check">
                <p className="feature-card__validation-note">{feature.validation_note}</p>
              </Collapsible>
            )}
            {feature.generated_code && (
              <Collapsible label="pandas code">
                <pre className="feature-card__code">
                  <code>{feature.generated_code}</code>
                </pre>
              </Collapsible>
            )}
          </div>
        </section>
      )}
    </Modal>
  );
}
