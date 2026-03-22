"use client";

import React, { useMemo } from "react";
import { motion } from "framer-motion";
import { Activity } from "lucide-react";
import type { DashboardData } from "@/types/dashboard";

interface HeartbeatMonitorProps {
  data: DashboardData;
  backendStatus: "connecting" | "connected" | "disconnected";
}

interface SourceStatus {
  key: string;
  label: string;
  count: number;
  fresh: boolean;
  ageSeconds: number;
}

const SOURCE_LABELS: Record<string, string> = {
  commercial_flights: "FLIGHTS",
  military_flights: "MILITARY",
  ships: "MARITIME",
  satellites: "ORBITAL",
  earthquakes: "SEISMIC",
  gdelt: "CONFLICT",
  firms_fires: "FIRES",
  cctv: "CCTV",
  kiwisdr: "SDR",
  internet_outages: "NET",
};

// How many seconds old before a source is considered stale
const STALE_THRESHOLD_S = 300; // 5 minutes

const HeartbeatMonitor = React.memo(function HeartbeatMonitor({
  data,
  backendStatus,
}: HeartbeatMonitorProps) {
  const sources: SourceStatus[] = useMemo(() => {
    const freshness = data?.freshness || {};
    const now = Date.now();

    return Object.entries(SOURCE_LABELS).map(([key, label]) => {
      const items = data?.[key as keyof DashboardData];
      const count = Array.isArray(items) ? items.length : 0;
      const ts = freshness[key];
      let ageSeconds = 9999;
      if (ts) {
        const parsed = new Date(ts + (ts.endsWith("Z") ? "" : "Z")).getTime();
        ageSeconds = Math.floor((now - parsed) / 1000);
      }
      return {
        key,
        label,
        count,
        fresh: ageSeconds < STALE_THRESHOLD_S,
        ageSeconds,
      };
    });
  }, [data]);

  const totalSources = sources.length;
  const activeSources = sources.filter((s) => s.count > 0).length;
  const freshSources = sources.filter((s) => s.fresh && s.count > 0).length;

  const statusColor =
    backendStatus === "disconnected"
      ? "#ef4444"
      : freshSources >= activeSources * 0.8
        ? "#22c55e"
        : freshSources >= activeSources * 0.5
          ? "#eab308"
          : "#f97316";

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="pointer-events-auto flex items-center gap-1.5"
    >
      {/* Heartbeat icon */}
      <div className="relative">
        <Activity size={10} style={{ color: statusColor }} />
        <div
          className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full animate-pulse"
          style={{ backgroundColor: statusColor }}
        />
      </div>

      {/* Source dots */}
      <div className="flex items-center gap-[3px]">
        {sources.map((s) => (
          <div
            key={s.key}
            title={`${s.label}: ${s.count} items (${s.ageSeconds < 9999 ? `${s.ageSeconds}s ago` : "no data"})`}
            className="w-1.5 h-1.5 rounded-full transition-colors duration-300"
            style={{
              backgroundColor:
                s.count === 0
                  ? "#374151" // gray — no data
                  : s.fresh
                    ? "#22c55e" // green — fresh
                    : "#eab308", // yellow — stale
            }}
          />
        ))}
      </div>

      {/* Summary */}
      <span className="text-[8px] font-mono text-[var(--text-muted)] tracking-wider">
        {activeSources}/{totalSources}
      </span>
    </motion.div>
  );
});

export default HeartbeatMonitor;
