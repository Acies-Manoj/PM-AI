import type { DataPreview } from "../api/audit";
import ExcelTable from "./ExcelTable";
import "./DataPreviewTable.css";

interface DataPreviewTableProps {
  preview: DataPreview;
}

export default function DataPreviewTable({ preview }: DataPreviewTableProps) {
  return (
    <div className="data-preview">
      <p className="data-preview__caption">
        Showing {preview.preview_row_count.toLocaleString()} of {preview.row_count.toLocaleString()} rows, all{" "}
        {preview.columns.length} columns (including the engineered features).
      </p>
      <ExcelTable columns={preview.columns} rows={preview.rows} />
    </div>
  );
}
