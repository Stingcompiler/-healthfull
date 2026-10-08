import { Plus } from "lucide-react";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";

/**
 * Empty state of an administration list that has no rows yet (not a search that found
 * nothing): what the list holds, and the button that adds the first row.
 */
export function ListEmpty({
  icon,
  title,
  description,
  actionLabel,
  actionIcon = <Plus />,
  onAction,
}: {
  icon: ReactNode;
  title: ReactNode;
  description: ReactNode;
  actionLabel?: ReactNode;
  actionIcon?: ReactNode;
  onAction?: () => void;
}) {
  return (
    <EmptyState
      bare
      size="compact"
      icon={icon}
      title={title}
      description={description}
      action={
        actionLabel && onAction ? (
          <Button variant="outline" onClick={onAction}>
            {actionIcon}
            {actionLabel}
          </Button>
        ) : undefined
      }
    />
  );
}
