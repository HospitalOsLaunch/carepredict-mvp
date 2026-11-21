import type { ComparisonObjective, ResourceFamily, ResourceIndicator } from "../api/worldModel";

export const familyName: Record<ResourceFamily, string> = {
  transport: "Transport", cleaning: "Bionettoyage", staffing: "Personnel IDE et AS",
  smr: "Soins médicaux et de réadaptation (SMR)", beds: "Lits",
};
export const indicatorName: Record<ResourceIndicator, string> = {
  uncovered_ide_minutes: "Soins infirmiers non couverts (min)",
  uncovered_as_minutes: "Soins aides-soignants non couverts (min)",
  bed_wait_patient_hours: "Attente d’un lit (heures-patients)",
  cost_eur: "Coût de l’affectation (€)",
};
export const objectives: Record<ComparisonObjective, { label: string; column: string; unit: string; description: string }> = {
  transfer_queue: {
    label: "File de transfert à 16 h", column: "File à 16 h", unit: "patients",
    description: "La file de transfert à 16 h est estimée en équivalents patients.",
  },
  bed_wait: {
    label: "Attente d’un lit de 12 h à 16 h", column: "Attente d’un lit", unit: "heures-patients",
    description: "L’attente cumulée additionne le temps passé par chaque patient à attendre un lit entre midi et 16 h.",
  },
  uncovered_care: {
    label: "Soins IDE et AS non couverts de 12 h à 16 h", column: "Soins non couverts", unit: "minutes",
    description: "Le total additionne les minutes de soins infirmiers et aides-soignants non couvertes entre midi et 16 h.",
  },
};

const numeric = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 });
export const signed = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2, signDisplay: "exceptZero" });
export const n = (x: number) => numeric.format(x);
export const time = (x: number) => `${x} h`;
