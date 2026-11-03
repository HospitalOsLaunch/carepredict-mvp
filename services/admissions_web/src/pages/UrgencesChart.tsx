import { Area, Bar, CartesianGrid, Cell, ComposedChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ErrorNote, Spinner } from "../components/common";
import { fmtNum, fmtShort } from "../lib/format";
import { useBoarding } from "../lib/liscop";

export function BoardingChart({ siteId }: { siteId: number }) {
  const series = useBoarding(siteId, 90);
  const days = series.data?.days ?? [];
  const declared = days.filter((d) => d.source === "declaration").length;
  const peak = days.reduce((m, d) => Math.max(m, d.boarding), 0);
  const data = days.map((d) => ({ ...d, label: fmtShort(d.day) }));
  return (
    <section className="panel px-5 py-4" aria-labelledby="boarding-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="boarding-title">Lits brancards à 10 h, 90 derniers jours</h2>
        <p className="text-[13px] text-ink-faint">
          Pic : {fmtNum(peak)} · {declared ? `${declared} jour(s) déclaré(s) à la main` : "tout est calculé"}
        </p>
      </div>
      {series.isLoading ? (
        <Spinner />
      ) : series.error ? (
        <ErrorNote error={series.error} />
      ) : (
        <div className="mt-3 h-72" role="img" aria-label={`Histogramme des lits brancards à 10 h sur ${days.length} jours, pic à ${peak}.`}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
              <CartesianGrid stroke="#D9E0F5" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 12, fill: "#666490" }} interval="preserveStartEnd" minTickGap={24} />
              <YAxis tick={{ fontSize: 12, fill: "#666490" }} allowDecimals={false} width={36} />
              <Tooltip
                formatter={(value, name) => [value, name]}
                labelFormatter={(label, payload) => {
                  const p = payload?.[0]?.payload as { source?: string } | undefined;
                  return p?.source === "declaration" ? `${label} (déclaré)` : String(label);
                }}
              />
              <Area
                dataKey="waiting_bed"
                name="En attente de lit à 10 h"
                type="stepAfter"
                fill="#ECE8FF"
                stroke="#B9AAFB"
                isAnimationActive={false}
              />
              <Bar dataKey="boarding" name="Lits brancards à 10 h" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                {data.map((d) => (
                  <Cell key={d.day} fill={d.source === "declaration" ? "#FFB21E" : "#FF6B57"} />
                ))}
              </Bar>
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-ink-soft">
        <span className="inline-flex items-center gap-1">
          <span className="h-3 w-3 rounded-sm bg-coral" aria-hidden /> calculé
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-3 w-3 rounded-sm bg-sun" aria-hidden /> déclaré à la main
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-3 w-3 rounded-sm border border-violet/40 bg-violet-soft" aria-hidden /> en attente de lit à 10 h
        </span>
      </p>
    </section>
  );
}
