import { useState, type ReactNode } from "react";
import { Area, AreaChart, CartesianGrid, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import {
  DataTable,
  DeltaText,
  ExecutiveSummaryBand,
  GaugeCard,
  HeatmapGrid,
  MiniBar,
  PressureBadge,
  RecommendedActionCard,
  SegmentedToggle,
  Sparkline,
  StatCard,
  type HorizonOption
} from "../components/design-system";
import {
  calmSparkline,
  heatmapCells,
  heatmapHours,
  heatmapUnits,
  sparkline,
  statVariants,
  tableColumns,
  tableRows
} from "../dev/galleryData";

const largeChartData = [
  { hour: "08", pressure: 58, careLoad: 52 },
  { hour: "10", pressure: 63, careLoad: 57 },
  { hour: "12", pressure: 71, careLoad: 66 },
  { hour: "14", pressure: 82, careLoad: 74 },
  { hour: "16", pressure: 88, careLoad: 78 },
  { hour: "18", pressure: 84, careLoad: 75 },
  { hour: "20", pressure: 76, careLoad: 69 }
];

export function ComponentGallery() {
  const [horizon, setHorizon] = useState<HorizonOption>("24H");

  return (
    <div className="mx-auto max-w-[1180px] space-y-7">
      <header className="flex items-end justify-between gap-6">
        <div>
          <p className="text-card-label text-brand-primary">Design-system gate</p>
          <h1 className="text-screen mt-2 text-text-strong">HospitalOS component gallery</h1>
          <p className="text-caption mt-2 max-w-3xl">
            Every reusable dashboard primitive is shown on deterministic mock data before any operational screen is assembled.
          </p>
        </div>
        <SegmentedToggle value={horizon} onChange={setHorizon} />
      </header>

      <GallerySection title="1. StatCard variants" description="Label, icon, hero number, unit, sub-caption and status-tinted sparkline.">
        <div className="grid grid-cols-6 gap-4">
          {statVariants.map((item) => (
            <StatCard key={item.label} {...item} sparkline={item.variant === "good" ? calmSparkline : sparkline} />
          ))}
        </div>
      </GallerySection>

      <GallerySection title="2. GaugeCard" description="Semicircular pressure gauge with band color, center score and trend context.">
        <div className="grid grid-cols-3 gap-4">
          <GaugeCard title="Hospital Pressure Score" value={72} label="High" variant="high" trend={sparkline} yesterday={58} sevenDayAverage={54} />
          <GaugeCard title="ICU Pressure Score" value={91} label="Very High" variant="critical" trend={sparkline} yesterday={79} sevenDayAverage={74} />
          <GaugeCard title="Pediatrics Pressure Score" value={44} label="Optimal" variant="optimal" trend={calmSparkline} yesterday={47} sevenDayAverage={49} />
        </div>
      </GallerySection>

      <GallerySection title="3. Interactive large chart" description="Large charts use Recharts tooltips, active points and crosshair. Decorative sparklines remain static SVGs.">
        <div className="rounded-card border border-border-subtle bg-bg-card p-5 shadow-card">
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={largeChartData} margin={{ top: 10, right: 16, bottom: 0, left: -16 }}>
              <defs>
                <linearGradient id="pressureFill" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor="var(--status-high)" stopOpacity={0.18} />
                  <stop offset="100%" stopColor="var(--status-high)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--border-subtle)" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="hour" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
              <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
              <Tooltip
                cursor={{ stroke: "var(--brand-primary)", strokeWidth: 1, strokeDasharray: "3 3" }}
                contentStyle={{ borderRadius: 10, borderColor: "var(--border-subtle)", boxShadow: "var(--shadow-card)", fontFamily: "Geist", fontSize: 11 }}
                itemStyle={{ color: "var(--text-body)", fontWeight: 600 }}
                labelStyle={{ color: "var(--text-muted)", fontWeight: 500 }}
              />
              <Area type="monotone" dataKey="pressure" name="Pressure" stroke="var(--status-high)" strokeWidth={2} fill="url(#pressureFill)" activeDot={{ r: 5 }} />
              <Line type="monotone" dataKey="careLoad" name="Care Load" stroke="var(--brand-primary)" strokeWidth={2} dot={false} activeDot={{ r: 5 }} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </GallerySection>

      <GallerySection title="4. SegmentedToggle and PressureBadge" description="Keyboard-accessible horizon selector and non-color-only pressure badges.">
        <div className="flex flex-wrap items-center gap-4 rounded-card border border-border-subtle bg-bg-card p-5 shadow-card">
          <SegmentedToggle value={horizon} onChange={setHorizon} />
          <PressureBadge status="critical" score={91} />
          <PressureBadge status="high" score={76} />
          <PressureBadge status="elevated" score={63} />
          <PressureBadge status="optimal" score={42} />
          <PressureBadge status="good" label="Improving" />
        </div>
      </GallerySection>

      <GallerySection title="5. DataTable" description="Dense table with status badges, mini bars, sparklines, deltas, action affordances and footer link.">
        <DataTable columns={tableColumns} rows={tableRows} footerLink="View all units" />
      </GallerySection>

      <GallerySection title="6. RecommendedActionCard" description="Numbered action cards with operational and financial metric pairs.">
        <div className="grid grid-cols-3 gap-4">
          <RecommendedActionCard rank={1} title="Open discharge lounge overflow" subtitle="Emergency Department · before 11:00" pressureDelta="↓ 18 pts" financialImpact="€12.4k" />
          <RecommendedActionCard rank={2} title="Redeploy two float nurses" subtitle="ICU and Cardiology · next shift" pressureDelta="↓ 11 pts" financialImpact="€7.8k" />
          <RecommendedActionCard rank={3} title="Advance confirmed transports" subtitle="Surgery · by 15:00" pressureDelta="↓ 8 pts" financialImpact="€5.2k" />
        </div>
      </GallerySection>

      <GallerySection title="7. HeatmapGrid" description="Unit-by-hour risk grid with keyboard and hover tooltips.">
        <HeatmapGrid units={heatmapUnits} hours={heatmapHours} cells={heatmapCells} />
      </GallerySection>

      <GallerySection title="8. ExecutiveSummaryBand" description="Executive paragraph plus Where / Why / What-to-do mini-columns.">
        <ExecutiveSummaryBand
          summary="Pressure is expected to concentrate in the Emergency Department and ICU between 14:00 and 20:00, driven by admission inflow and delayed discharges. The strongest near-term lever is discharge acceleration before the afternoon peak."
          columns={[
            { label: "Where", value: "Emergency Department, ICU and Cardiology show the highest near-term pressure." },
            { label: "Why", value: "Admission inflow exceeds discharge velocity while night staffing coverage tightens." },
            { label: "What to do", value: "Simulate discharge acceleration and float-pool redeployment before 11:00." }
          ]}
        />
      </GallerySection>

      <GallerySection title="9. Primitives" description="Sparkline, MiniBar and DeltaText compose the denser components.">
        <div className="grid grid-cols-3 gap-4 rounded-card border border-border-subtle bg-bg-card p-5 shadow-card">
          <div>
            <p className="text-card-label mb-3">Sparkline</p>
            <Sparkline data={sparkline} variant="high" label="High pressure primitive trend" />
          </div>
          <div>
            <p className="text-card-label mb-3">MiniBar</p>
            <MiniBar value={82} label="Bed saturation" />
          </div>
          <div>
            <p className="text-card-label mb-3">DeltaText</p>
            <div className="flex gap-4">
              <DeltaText value={18} unit="pts" inverted />
              <DeltaText value={-12} unit="pts" inverted />
            </div>
          </div>
        </div>
      </GallerySection>
    </div>
  );
}

interface GallerySectionProps {
  title: string;
  description: string;
  children: ReactNode;
}

function GallerySection({ title, description, children }: GallerySectionProps) {
  return (
    <section className="space-y-4" aria-labelledby={slug(title)}>
      <div>
        <h2 id={slug(title)} className="text-section text-text-strong">
          {title}
        </h2>
        <p className="text-caption mt-1">{description}</p>
      </div>
      {children}
    </section>
  );
}

function slug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-");
}
