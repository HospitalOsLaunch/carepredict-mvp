import {
  Area,
  CartesianGrid,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  ComposedChart
} from "recharts";

import type { ChartPoint } from "../api/types";

interface ChargeChartProps {
  data: ChartPoint[];
}

export function ChargeChart({ data }: ChargeChartProps) {
  return (
    <section className="chart-panel" aria-label="Historique et prédiction">
      <ResponsiveContainer width="100%" height={360}>
        <ComposedChart data={data} margin={{ top: 16, right: 20, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#d9dee8" />
          <XAxis
            dataKey="timestamp"
            tickFormatter={(value: string) =>
              new Intl.DateTimeFormat("fr-FR", { hour: "2-digit" }).format(new Date(value))
            }
          />
          <YAxis domain={["dataMin - 8", "dataMax + 8"]} />
          <Tooltip
            labelFormatter={(value) =>
              new Intl.DateTimeFormat("fr-FR", {
                hour: "2-digit",
                minute: "2-digit",
                day: "2-digit",
                month: "2-digit"
              }).format(new Date(String(value)))
            }
          />
          <Legend />
          <Area
            type="monotone"
            dataKey="upper_90"
            stroke="none"
            fill="#8fb8ff"
            fillOpacity={0.22}
            name="Bande haute 90%"
          />
          <Area
            type="monotone"
            dataKey="lower_90"
            stroke="none"
            fill="#ffffff"
            fillOpacity={1}
            name="Bande basse 90%"
          />
          <Line
            type="monotone"
            dataKey="historical"
            stroke="#5c6470"
            strokeWidth={2}
            dot={false}
            name="Historique 24h"
          />
          <Line
            type="monotone"
            dataKey="predicted"
            stroke="#176b87"
            strokeWidth={3}
            dot={false}
            name="Prédiction 12h"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </section>
  );
}
