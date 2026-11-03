import * as SheetPrimitive from "@radix-ui/react-dialog";
import { cva, type VariantProps } from "class-variance-authority";
import { X } from "lucide-react";
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from "react";

import { cn } from "@/lib/utils";

// shadcn/ui Sheet: a Radix dialog that slides in from an edge (the mobile « Plus » panel
// comes up from the bottom bar it was opened from).
export const Sheet = SheetPrimitive.Root;
export const SheetTrigger = SheetPrimitive.Trigger;
export const SheetClose = SheetPrimitive.Close;
export const SheetTitle = SheetPrimitive.Title;
export const SheetDescription = SheetPrimitive.Description;

const sheetVariants = cva(
  "fixed z-50 bg-paper text-ink shadow-2xl transition ease-out data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:duration-150 data-[state=open]:duration-200",
  {
    variants: {
      side: {
        bottom: "inset-x-0 bottom-0 rounded-t-[24px] data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom",
        right: "inset-y-0 right-0 h-full w-3/4 max-w-sm data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right"
      }
    },
    defaultVariants: { side: "bottom" }
  }
);

export const SheetContent = forwardRef<
  ElementRef<typeof SheetPrimitive.Content>,
  ComponentPropsWithoutRef<typeof SheetPrimitive.Content> & VariantProps<typeof sheetVariants> & { closeLabel?: string }
>(({ side, className, children, closeLabel = "Fermer", ...props }, ref) => (
  <SheetPrimitive.Portal>
    <SheetPrimitive.Overlay className="fixed inset-0 z-50 bg-ink/40 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
    <SheetPrimitive.Content ref={ref} className={cn(sheetVariants({ side }), className)} {...props}>
      {children}
      <SheetPrimitive.Close
        className="touch-target absolute right-3 top-3 grid h-11 w-11 place-items-center rounded-chip text-ink transition-colors hover:bg-sky"
        aria-label={closeLabel}
      >
        <X className="h-5 w-5" aria-hidden />
      </SheetPrimitive.Close>
    </SheetPrimitive.Content>
  </SheetPrimitive.Portal>
));
SheetContent.displayName = SheetPrimitive.Content.displayName;
