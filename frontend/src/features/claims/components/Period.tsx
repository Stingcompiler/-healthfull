import { DateText } from "@/components/DateText";

/** The period of a claim, "from – to". */
export function Period({ start, end }: { start: string; end: string }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1">
      <DateText value={start} />
      <span aria-hidden="true">–</span>
      <DateText value={end} />
    </span>
  );
}
