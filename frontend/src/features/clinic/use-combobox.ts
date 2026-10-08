import { useId, useState, type KeyboardEvent } from "react";

export interface ComboboxOptions<T> {
  /** What the input shows now. */
  query: string;
  /** The (debounced) term the results were asked for. */
  term: string;
  /** Run the search for the input as it is now (flushes the debounce). */
  search: (term: string) => void;
  results: readonly T[];
  /**
   * Whether `results` answer `term` (not data kept from the previous query while the new one
   * loads). Enter never picks from results that are not fresh.
   */
  settled: boolean;
  onPick: (item: T) => void;
  /** Escape with text in the box: clear the query and term (which also closes the list). */
  onEscape?: () => void;
  /** The highlight goes back to the first row when this changes (default: the term). */
  resetKey?: string;
}

/**
 * A search box with a result list as an ARIA combobox: ArrowUp/ArrowDown move the highlighted
 * option, Enter adds it, Escape clears the box and closes the list, and Enter never takes a row of
 * an earlier query (typed fast, or a filter just changed). The input points at the list
 * (aria-controls) only while the list is on screen. Returns props for the input, the list and
 * each option.
 */
export function useCombobox<T>({
  query,
  term,
  search,
  results,
  settled,
  onPick,
  onEscape,
  resetKey,
}: ComboboxOptions<T>) {
  const listId = useId();
  const key = resetKey ?? term;
  const [highlight, setHighlight] = useState({ key, index: 0 });
  const active = highlight.key === key ? Math.min(highlight.index, Math.max(results.length - 1, 0)) : 0;
  const setActive = (next: number | ((i: number) => number)) => {
    setHighlight({ key, index: typeof next === "function" ? next(active) : next });
  };
  const fresh = settled && query.trim() === term;

  const optionId = (index: number) => `${listId}-opt-${String(index)}`;
  const expanded = results.length > 0;

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      if (!query && !term) return;
      event.preventDefault();
      onEscape?.();
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!expanded) return;
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((i) => (i + step + results.length) % results.length);
      return;
    }
    if (event.key !== "Enter") return;
    event.preventDefault();
    if (!fresh) {
      // The list on screen belongs to another query: search now and let the user confirm.
      if (query.trim() !== term) search(query.trim());
      return;
    }
    const item = results[active];
    if (item !== undefined) onPick(item);
  };

  return {
    fresh,
    active,
    setActive,
    inputProps: {
      role: "combobox",
      "aria-autocomplete": "list" as const,
      "aria-expanded": expanded,
      "aria-controls": expanded ? listId : undefined,
      "aria-activedescendant": expanded && fresh ? optionId(active) : undefined,
      onKeyDown,
    },
    listProps: { id: listId, role: "listbox" },
    optionProps: (index: number) => ({
      id: optionId(index),
      role: "option",
      "aria-selected": index === active,
      // Keep focus in the input when an option is clicked.
      onMouseDown: (event: { preventDefault: () => void }) => {
        event.preventDefault();
      },
      onMouseEnter: () => {
        setActive(index);
      },
    }),
  };
}
