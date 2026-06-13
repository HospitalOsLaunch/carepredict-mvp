export interface NavigationItem {
  path: string;
  label: string;
  icon: string;
  description: string;
}

export const navigationItems: NavigationItem[] = [
  { path: "/", label: "Overview", icon: "⌁", description: "Operational Pressure Forecast" },
  { path: "/forecast", label: "Pressure Forecast", icon: "⌁", description: "Multi-horizon pressure and unit risk" },
  { path: "/actions", label: "Action Engine", icon: "✓", description: "Prioritized operational actions" },
  { path: "/simulation", label: "Simulation", icon: "◇", description: "Counterfactual operational planning" },
  { path: "/beds", label: "Beds", icon: "▦", description: "Capacity, blockers, admissions and discharges" },
  { path: "/staffing", label: "Staffing", icon: "◌", description: "Coverage, gaps and redeployment" },
  { path: "/flow", label: "Patient Flow", icon: "→", description: "ED-to-discharge throughput" },
  { path: "/or-ed", label: "OR / ED", icon: "＋", description: "Operating room and emergency pressure" },
  { path: "/reports", label: "Reports", icon: "▤", description: "Operational trend reporting" }
];
