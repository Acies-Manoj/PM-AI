import type { AnalysisTreeNode } from "../utils/analysisTree";
import AnalysisCard from "./AnalysisCard";
import { IconSparkle } from "./icons";
import "./AnalysisEntryTree.css";

interface AnalysisEntryTreeProps {
  node: AnalysisTreeNode;
  depth: number;
  runningIds: Record<string, boolean>;
  runFailures: Record<string, string | undefined>;
  onRun: (entry: AnalysisTreeNode["entry"]) => void;
  onExpand: (entryId: string) => void;
}

/** Renders one analysis card, then -- directly beneath it, indented and
 * connected by a rule -- whichever follow-up analyses were drilled into
 * from it, each recursing through this same component. A drilldown's chart
 * always sits under its own parent's, however many levels deep, instead of
 * living in an unrelated flat list elsewhere on the page. Each card itself
 * stays compact (chart + one-line summary) -- the full interpretation and
 * any not-yet-explored drilldown suggestions only show in the detail modal
 * (AnalysisCard's "View details" button), not inline on the page. */
export default function AnalysisEntryTree({ node, depth, runningIds, runFailures, onRun, onExpand }: AnalysisEntryTreeProps) {
  const { entry, children } = node;

  return (
    <div className={`analysis-tree__node ${depth > 0 ? "analysis-tree__node--nested" : ""}`}>
      <AnalysisCard
        entry={entry}
        running={!!runningIds[entry.id]}
        runFailure={runFailures[entry.id]}
        onRun={() => onRun(entry)}
        onExpand={() => onExpand(entry.id)}
      />

      {children.length > 0 && (
        <div className="analysis-tree__children">
          <span className="analysis-tree__children-label">
            <IconSparkle /> {children.length === 1 ? "Drilldown" : `${children.length} drilldowns`} from this analysis
          </span>
          {children.map((child) => (
            <AnalysisEntryTree key={child.entry.id} node={child} depth={depth + 1} runningIds={runningIds} runFailures={runFailures} onRun={onRun} onExpand={onExpand} />
          ))}
        </div>
      )}
    </div>
  );
}
