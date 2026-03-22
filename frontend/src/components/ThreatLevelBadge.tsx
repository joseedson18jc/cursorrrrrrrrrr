"use client";

import React, { useEffect, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Shield, ChevronDown, ChevronUp } from "lucide-react";
import { API_BASE } from "@/lib/api";

interface ThreatData {
  level: number;
  name: string;
  color: string;
  signals: Record<string, number>;
  signal_scores: Record<string, number>;
}

const SIGNAL_LABELS: Record<string, string> = {
  military_flights: "MIL FLIGHTS",
  earthquakes_m5plus: "SEISMIC M5+",
  gps_jamming_zones: "GPS JAMMING",
  conflict_events: "CONFLICT EVENTS",
  fire_hotspots: "FIRE HOTSPOTS",
  internet_outages: "NET OUTAGES",
};

const ThreatLevelBadge = React.memo(function ThreatLevelBadge() {
  const [threat, setThreat] = useState<ThreatData | null>(null);
  const [expanded, setExpanded] = useState(false);

  const fetchThreat = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/threat-level`);
      if (res.ok) {
        setThreat(await res.json());
      }
    } catch {
      // Silently fail — badge just won't update
    }
  }, []);

  useEffect(() => {
    fetchThreat();
    const interval = setInterval(fetchThreat, 30000);
    return () => clearInterval(interval);
  }, [fetchThreat]);

  if (!threat) return null;

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      className="pointer-events-auto"
    >
      <div
        className="bg-[var(--bg-primary)]/80 backdrop-blur-md border rounded-lg overflow-hidden cursor-pointer"
        style={{ borderColor: `${threat.color}40` }}
        onClick={() => setExpanded(!expanded)}
      >
        {/* Main badge */}
        <div className="flex items-center gap-2 px-3 py-2">
          <div
            className="w-2 h-2 rounded-full animate-pulse"
            style={{ backgroundColor: threat.color }}
          />
          <Shield size={12} style={{ color: threat.color }} />
          <span className="text-[9px] font-mono tracking-[0.15em] text-[var(--text-muted)]">
            THREATCON
          </span>
          <span
            className="text-[10px] font-mono font-bold tracking-widest"
            style={{ color: threat.color }}
          >
            {threat.name}
          </span>
          <span
            className="text-[11px] font-mono font-bold ml-1 w-4 h-4 rounded flex items-center justify-center"
            style={{ backgroundColor: `${threat.color}20`, color: threat.color }}
          >
            {threat.level}
          </span>
          {expanded ? (
            <ChevronUp size={10} className="text-[var(--text-muted)]" />
          ) : (
            <ChevronDown size={10} className="text-[var(--text-muted)]" />
          )}
        </div>

        {/* Expanded signal breakdown */}
        <AnimatePresence>
          {expanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="border-t px-3 py-2 space-y-1"
              style={{ borderColor: `${threat.color}20` }}
            >
              {Object.entries(threat.signals).map(([key, value]) => {
                const score = threat.signal_scores[key] || 0;
                const barWidth = Math.min(100, (score / 4) * 100);
                return (
                  <div key={key} className="flex items-center gap-2">
                    <span className="text-[8px] font-mono text-[var(--text-muted)] w-24 truncate">
                      {SIGNAL_LABELS[key] || key}
                    </span>
                    <div className="flex-1 h-1 bg-[var(--bg-secondary)] rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{
                          width: `${barWidth}%`,
                          backgroundColor: threat.color,
                        }}
                      />
                    </div>
                    <span className="text-[8px] font-mono text-[var(--text-muted)] w-8 text-right">
                      {value}
                    </span>
                  </div>
                );
              })}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
});

export default ThreatLevelBadge;
