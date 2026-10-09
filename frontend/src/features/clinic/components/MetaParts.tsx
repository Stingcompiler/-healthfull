import { Fragment } from "react";

/**
 * Short facts joined by a middle dot, each isolated (<bdi>) so a Latin dose such as "1 tablet"
 * keeps its order inside Arabic text.
 */
export function MetaParts({ parts }: { parts: readonly (string | null | undefined | false)[] }) {
  const shown = parts.filter((p): p is string => typeof p === "string" && p.trim() !== "");
  return (
    <>
      {shown.map((part, i) => (
        <Fragment key={`${String(i)}-${part}`}>
          {i > 0 ? " · " : null}
          <bdi>{part}</bdi>
        </Fragment>
      ))}
    </>
  );
}
