import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

// shadcn/ui Button on the HospitalOS tokens. The variants are those of the former .btn-*
// classes (index.css), which unmigrated screens still use.
export const buttonVariants = cva(
  "touch-target inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-chip font-bold transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-violet text-white hover:bg-violet-dark",
        sun: "bg-sun text-ink hover:bg-sun-glow",
        dark: "bg-ink text-white hover:bg-ink-soft",
        quiet: "bg-sky text-ink hover:bg-sky-deep",
        ghost: "bg-transparent text-ink hover:bg-sky",
        danger: "bg-coral-soft text-coral-dark hover:bg-coral-dark hover:text-white"
      },
      size: {
        default: "px-4 py-2 text-[15px]",
        sm: "px-3 py-1.5 text-[14px]",
        icon: "h-9 w-9 p-0"
      }
    },
    defaultVariants: { variant: "primary", size: "default" }
  }
);

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  /** Render the child (a router Link…) with the button's look instead of a <button>. */
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : "button";
  return <Comp ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />;
});
Button.displayName = "Button";
