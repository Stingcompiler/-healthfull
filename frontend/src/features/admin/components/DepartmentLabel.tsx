import { useDepartmentById, useLocalName } from "../hooks";
import { Code } from "./FormDialog";

/** A department in a table cell: its name in the UI language, with the code beneath it. */
export function DepartmentLabel({ id, code }: { id: number | null | undefined; code: string | null | undefined }) {
  const departmentById = useDepartmentById();
  const localName = useLocalName();
  if (id === null || id === undefined) return <span className="text-muted">—</span>;
  const department = departmentById(id);
  if (!department) return <Code>{code}</Code>;
  return (
    <div className="min-w-0">
      <div className="truncate text-fg">{localName(department)}</div>
      <Code>{code}</Code>
    </div>
  );
}
