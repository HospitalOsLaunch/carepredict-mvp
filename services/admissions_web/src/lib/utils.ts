import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// The design tokens of tailwind.config.cjs that tailwind-merge cannot guess: without them, a
// rounded-chip passed to a component would not replace its default rounded-xl.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      rounded: [{ rounded: ["panel", "chip"] }],
      shadow: [{ shadow: ["lift"] }]
    }
  }
});

/** shadcn/ui's class combiner: conditional classes, later ones win over earlier ones. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
