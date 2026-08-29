import {
  Activity,
  Bed,
  FileText,
  GitBranch,
  History,
  LayoutDashboard,
  LucideIcon,
  PlusSquare,
  Users,
  Workflow,
  Zap
} from "lucide-react";

export interface NavigationItem {
  path: string;
  label: string;
  icon: LucideIcon;
  description: string;
}

export const navigationItems: NavigationItem[] = [
  { path: "/", label: "Overview", icon: LayoutDashboard, description: "Operational Pressure Forecast" },
  { path: "/forecast", label: "Pressure Forecast", icon: Activity, description: "Multi-horizon pressure and unit risk" },
  { path: "/actions", label: "Action Engine", icon: Zap, description: "Prioritized operational actions" },
  { path: "/simulation", label: "Simulation", icon: GitBranch, description: "Counterfactual operational planning" },
  { path: "/beds", label: "Beds", icon: Bed, description: "Capacity, blockers, admissions and discharges" },
  { path: "/staffing", label: "Staffing", icon: Users, description: "Coverage, gaps and redeployment" },
  { path: "/flow", label: "Patient Flow", icon: Workflow, description: "ED-to-discharge throughput" },
  { path: "/or-ed", label: "OR / ED", icon: PlusSquare, description: "Operating room and emergency pressure" },
  { path: "/reports", label: "Reports", icon: FileText, description: "Operational trend reporting" }
];

export const researchNavigationItems: NavigationItem[] = [
  { path: "/insights", label: "Insights", icon: LayoutDashboard, description: "Situations et recommandations à décider" },
  { path: "/actions", label: "Actions", icon: Zap, description: "Décisions enregistrées et à examiner" },
  { path: "/history", label: "Historique", icon: History, description: "Historique des décisions de recherche" }
];

export const legacyNavigationItem = {
  path: "/legacy",
  label: "Legacy TFT",
  icon: History
};
