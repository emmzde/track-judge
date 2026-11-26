import React from "react";
import * as Dialog from "@radix-ui/react-dialog";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import { X } from "lucide-react";
import { cva } from "class-variance-authority";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import { InterfaceIcon } from "./icons";

const button = cva(
  "btn inline-flex items-center justify-center gap-2 font-semibold",
  {
    variants: {
      variant: {
        default: "btn-primary",
        secondary: "btn-secondary",
        ghost: "btn-ghost",
        icon: "btn-icon",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export function Button({ variant, className, ...props }) {
  return (
    <button
      type="button"
      data-slot="button"
      className={twMerge(clsx(button({ variant }), className))}
      {...props}
    />
  );
}

export function Switch({
  label,
  hint,
  icon,
  checked,
  onCheckedChange,
  disabled,
}) {
  const id = React.useId();
  return (
    <label className="option" htmlFor={id}>
      <span className="option-icon">
        <InterfaceIcon name={icon} />
      </span>
      <span className="option-copy">
        <strong>{label}</strong>
        <small>{hint}</small>
      </span>
      <SwitchPrimitive.Root
        id={id}
        className="switch"
        aria-label={label}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
      >
        <SwitchPrimitive.Thumb className="switch-thumb" />
      </SwitchPrimitive.Root>
    </label>
  );
}

export function Modal({
  open,
  title,
  description,
  close,
  onClose,
  children,
  wide,
}) {
  const content = React.useRef(null);
  const returnFocus = React.useRef(null);
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="overlay" />
        <Dialog.Content
          ref={content}
          className={clsx("modal", wide && "modal-wide")}
          {...(!description && { "aria-describedby": undefined })}
          onOpenAutoFocus={(event) => {
            returnFocus.current = document.activeElement;
            const field = content.current?.querySelector(
              "[data-initial-focus]",
            );
            if (field) {
              event.preventDefault();
              field.focus({ preventScroll: true });
            }
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            returnFocus.current?.focus({ preventScroll: true });
          }}
        >
          <div className="row between">
            <Dialog.Title>{title}</Dialog.Title>
            <Dialog.Close asChild>
              <Button variant="icon" aria-label={close}>
                <X />
              </Button>
            </Dialog.Close>
          </div>
          {description && (
            <Dialog.Description>{description}</Dialog.Description>
          )}
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
