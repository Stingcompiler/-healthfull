import type { Workspace } from "../types";
import { DiagnosisSection } from "./DiagnosisSection";
import { NoteEditor } from "./NoteEditor";
import { ReferralSection } from "./ReferralSection";
import { VitalsSection } from "./VitalsSection";

/** The clinical note tab: note, diagnoses (ICD-10), vitals and referrals (FEATURES 3.3, 3.4, 3.9). */
export function NoteTab({ workspace }: { workspace: Workspace }) {
  const open = workspace.visit.status === "open";
  return (
    <div className="flex flex-col gap-4">
      <NoteEditor visitId={workspace.visit.id} notes={workspace.notes} open={open} />
      <DiagnosisSection visitId={workspace.visit.id} diagnoses={workspace.diagnoses} open={open} />
      <VitalsSection visitId={workspace.visit.id} vitals={workspace.vitals} open={open} />
      <ReferralSection visitId={workspace.visit.id} referrals={workspace.referrals} open={open} />
    </div>
  );
}
