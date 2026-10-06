import { CircleCheckIcon, InfoIcon, Loader2Icon, OctagonXIcon, TriangleAlertIcon } from "lucide-react";
import type * as React from "react";
import { Toaster as Sonner, type ToasterProps } from "sonner";

/**
 * Toast host. Colors come from the semantic tokens via CSS variables that
 * sonner reads; direction follows the document.
 */
function Toaster({ dir, theme, ...props }: ToasterProps) {
  return (
    <Sonner
      dir={dir}
      theme={theme}
      className="toaster group"
      position="top-center"
      icons={{
        success: <CircleCheckIcon className="size-4 text-success" />,
        info: <InfoIcon className="size-4 text-info" />,
        warning: <TriangleAlertIcon className="size-4 text-warning" />,
        error: <OctagonXIcon className="size-4 text-danger" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      toastOptions={{
        classNames: {
          toast: "font-sans !rounded-card !shadow-raised",
          description: "!text-muted",
        },
      }}
      style={
        {
          "--normal-bg": "var(--surface-raised)",
          "--normal-text": "var(--fg)",
          "--normal-border": "var(--card-border)",
          "--success-bg": "var(--success-bg)",
          "--success-text": "var(--success-fg)",
          "--success-border": "var(--success-border)",
          "--error-bg": "var(--danger-bg)",
          "--error-text": "var(--danger-fg)",
          "--error-border": "var(--danger-border)",
          "--warning-bg": "var(--warning-bg)",
          "--warning-text": "var(--warning-fg)",
          "--warning-border": "var(--warning-border)",
          "--info-bg": "var(--info-bg)",
          "--info-text": "var(--info-fg)",
          "--info-border": "var(--info-border)",
          "--border-radius": "var(--card-radius)",
        } as React.CSSProperties
      }
      richColors
      {...props}
    />
  );
}

export { Toaster };
