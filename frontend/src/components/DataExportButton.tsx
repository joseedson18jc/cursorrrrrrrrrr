"use client";

import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Download, FileJson, FileSpreadsheet, X } from "lucide-react";
import { API_BASE } from "@/lib/api";

const EXPORTABLE_LAYERS = [
  { key: "commercial_flights", label: "Commercial Flights" },
  { key: "military_flights", label: "Military Flights" },
  { key: "private_flights", label: "Private Flights" },
  { key: "private_jets", label: "Private Jets" },
  { key: "ships", label: "Ships" },
  { key: "satellites", label: "Satellites" },
  { key: "earthquakes", label: "Earthquakes" },
  { key: "firms_fires", label: "Fire Hotspots" },
  { key: "gps_jamming", label: "GPS Jamming" },
  { key: "internet_outages", label: "Internet Outages" },
  { key: "datacenters", label: "Data Centers" },
  { key: "military_bases", label: "Military Bases" },
  { key: "power_plants", label: "Power Plants" },
];

const DataExportButton = React.memo(function DataExportButton() {
  const [open, setOpen] = useState(false);
  const [selectedLayers, setSelectedLayers] = useState<Set<string>>(
    new Set(["commercial_flights", "military_flights", "ships"])
  );
  const [exporting, setExporting] = useState(false);

  const toggleLayer = (key: string) => {
    setSelectedLayers((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const doExport = async (format: "geojson" | "csv") => {
    setExporting(true);
    try {
      if (format === "geojson") {
        const layers = Array.from(selectedLayers).join(",");
        const res = await fetch(
          `${API_BASE}/api/export/geojson?layers=${encodeURIComponent(layers)}`
        );
        if (res.ok) {
          const blob = await res.blob();
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `shadowbroker-export-${Date.now()}.geojson`;
          a.click();
          URL.revokeObjectURL(url);
        }
      } else {
        // CSV — export each selected layer as separate file
        for (const layer of selectedLayers) {
          const res = await fetch(
            `${API_BASE}/api/export/csv?layer=${encodeURIComponent(layer)}`
          );
          if (res.ok) {
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `${layer}-${Date.now()}.csv`;
            a.click();
            URL.revokeObjectURL(url);
          }
        }
      }
    } catch (e) {
      console.error("Export failed:", e);
    }
    setExporting(false);
    setOpen(false);
  };

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 bg-[var(--bg-primary)]/60 backdrop-blur-md border border-[var(--border-primary)] rounded-lg px-3 py-1.5 text-[9px] font-mono tracking-[0.15em] text-[var(--text-muted)] hover:text-cyan-400 hover:border-cyan-800 transition-colors pointer-events-auto"
        title="Export data"
      >
        <Download size={10} />
        EXPORT
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm pointer-events-auto"
            onClick={() => setOpen(false)}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              onClick={(e) => e.stopPropagation()}
              className="bg-[var(--bg-primary)] border border-[var(--border-primary)] rounded-xl p-6 w-[360px] shadow-[0_0_40px_rgba(0,255,255,0.1)]"
            >
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Download size={14} className="text-cyan-400" />
                  <span className="text-xs font-mono tracking-widest text-[var(--text-primary)]">
                    DATA EXPORT
                  </span>
                </div>
                <button
                  onClick={() => setOpen(false)}
                  className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                >
                  <X size={14} />
                </button>
              </div>

              {/* Layer selection */}
              <div className="space-y-1 max-h-[300px] overflow-y-auto styled-scrollbar mb-4">
                {EXPORTABLE_LAYERS.map((l) => (
                  <label
                    key={l.key}
                    className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-[var(--bg-secondary)] cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={selectedLayers.has(l.key)}
                      onChange={() => toggleLayer(l.key)}
                      className="accent-cyan-500"
                    />
                    <span className="text-[10px] font-mono text-[var(--text-secondary)]">
                      {l.label}
                    </span>
                  </label>
                ))}
              </div>

              {/* Export buttons */}
              <div className="flex gap-2">
                <button
                  onClick={() => doExport("geojson")}
                  disabled={exporting || selectedLayers.size === 0}
                  className="flex-1 flex items-center justify-center gap-2 py-2 bg-cyan-950/40 border border-cyan-800/40 rounded-lg text-[10px] font-mono text-cyan-400 hover:bg-cyan-900/40 disabled:opacity-40 transition-colors"
                >
                  <FileJson size={12} />
                  {exporting ? "EXPORTING..." : "GEOJSON"}
                </button>
                <button
                  onClick={() => doExport("csv")}
                  disabled={exporting || selectedLayers.size === 0}
                  className="flex-1 flex items-center justify-center gap-2 py-2 bg-cyan-950/40 border border-cyan-800/40 rounded-lg text-[10px] font-mono text-cyan-400 hover:bg-cyan-900/40 disabled:opacity-40 transition-colors"
                >
                  <FileSpreadsheet size={12} />
                  {exporting ? "EXPORTING..." : "CSV"}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
});

export default DataExportButton;
