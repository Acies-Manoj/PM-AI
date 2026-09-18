const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type SampleSlotId = "sensiwatch" | "temperatureMatrix" | "lightMatrix" | "customerKpis" | "analysisProfile";

// Mirrors routers/samples.py's SAMPLE_FILES keys exactly -- known up front
// so this doesn't need to parse a Content-Disposition header back out.
const SAMPLE_SLOTS: SampleSlotId[] = ["sensiwatch", "temperatureMatrix", "lightMatrix", "customerKpis", "analysisProfile"];
const SAMPLE_FILENAMES: Record<SampleSlotId, string> = {
  sensiwatch: "tabular_shipment_data_sample.xlsm",
  temperatureMatrix: "temperature_matrix_sample.xlsx",
  lightMatrix: "light_matrix_sample.xlsx",
  customerKpis: "customer_kpi_profile_example.json",
  analysisProfile: "analysis_profile_example.json",
};

/** Dev convenience: fetches every bundled sample file (see
 * backend/data/raw/ and routers/samples.py) as a real File object, so the
 * Upload page's "Add all samples" button can feed them through the exact
 * same onSelect/setMatrixFiles path a manual file pick would -- nothing
 * downstream needs to know the files didn't come from a file input. */
export async function fetchAllSamples(): Promise<Record<SampleSlotId, File>> {
  const entries = await Promise.all(
    SAMPLE_SLOTS.map(async (slot) => {
      const response = await fetch(`${API_BASE_URL}/api/samples/${slot}`);
      if (!response.ok) {
        throw new Error(`Could not load the sample file for "${slot}" (HTTP ${response.status}).`);
      }
      const blob = await response.blob();
      return [slot, new File([blob], SAMPLE_FILENAMES[slot], { type: blob.type })] as const;
    })
  );
  return Object.fromEntries(entries) as Record<SampleSlotId, File>;
}
