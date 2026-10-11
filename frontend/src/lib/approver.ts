/** An approver typed at the desk, kept in plain state (`ApproverFieldset`, ADR 0009, 0022). */
export interface ApproverState {
  enabled: boolean;
  username: string;
  password: string;
}

export const NO_APPROVER: ApproverState = { enabled: false, username: "", password: "" };

/** The approver to send: credentials when (switched on or required and) filled, else none. */
export function approverPayload(
  state: ApproverState,
  { optional = true }: { optional?: boolean } = {},
): { username: string; password: string } | null {
  if ((optional && !state.enabled) || !state.username.trim() || !state.password) return null;
  return { username: state.username.trim(), password: state.password };
}
