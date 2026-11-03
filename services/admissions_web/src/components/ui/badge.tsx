import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

// shadcn/ui Badge on the HospitalOS tokens (the former .chip): every tone passes WCAG AA.
export const badgeVariants = cva("inline-flex items-center gap-1 rounded-chip px-2.5 py-0.5 text-[13px] font-bold", {
  variants: {
    tone: {
      neutral: "bg-sky-deep text-ink-soft",
      violet: "bg-violet-soft text-violet-dark",
      lagoon: "bg-lagoon-soft text-lagoon-dark",
      "lagoon-solid": "bg-lagoon-dark text-white",
      coral: "bg-coral-soft text-coral-dark",
      "coral-solid": "bg-coral-dark text-white",
      sun: "bg-sun-soft text-ink",
      ink: "bg-ink text-white"
    }
  },
  defaultVariants: { tone: "neutral" }
});

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
