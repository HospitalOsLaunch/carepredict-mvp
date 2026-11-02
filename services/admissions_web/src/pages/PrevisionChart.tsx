import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { ForecastSeries } from "../api/types_liscop";
import { fmtNum, fmtShort } from "../lib/format";
import { byHorizon, range } from "./PrevisionPage";

/** Boarding at 10:00: the last 28 observed days, then the forecast with its 80 % band. */
export function BoardingChart({ series }: { series: ForecastSeries }) {
  const points = [
    ...series.recent.map((r) => ({ label: fmtShort(r.day), observed: r.value })),
    ...series.values.map((v) => ({
      label: fmtShort(v.day),
      forecast: Math.round(v.mean * 10) / 10,
      band: [Math.round(v.q10), Math.round(v.q90)] as [number, number]
    }))
  ];
  const j1 = byHorizon(series, "J+1");
  return (
    <figure>
      <div
        className="h-64"
        role="img"
        aria-label={`Lits brancards à 10 h, ${series.label} : 28 derniers jours observés puis prévision ; demain ${
          j1 ? `${fmtNum(j1.mean)} attendus, de ${range(j1)}` : "non calculé"
        }.`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={points} margin={{ left: 0, right: 8, top: 8 }}>
            <CartesianGrid stroke="#D9E0F5" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 12, fill: "#7D7BA3" }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 12, fill: "#7D7BA3" }} width={36} allowDecimals={false} />
            <Tooltip />
            <Area dataKey="band" name="Fourchette à 80 %" fill="#ECE8FF" stroke="none" isAnimationActive={false} />
            <Line
              dataKey="observed"
              name="Observé"
              stroke="#0FA897"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="forecast"
              name="Prévu"
              stroke="#5B3DF5"
              strokeWidth={2}
              strokeDasharray="5 4"
              dot={{ r: 2 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-2 text-[13px] text-ink-soft">
        Patients présents aux urgences à 10 h, avec une décision d'hospitalisation et arrivés avant 8 h. Trait plein :
        observé ; pointillé : prévu, bande : fourchette à 80 %.
        {series.model && ` Modèle : ${series.model}.`}
      </figcaption>
    </figure>
  );
}
