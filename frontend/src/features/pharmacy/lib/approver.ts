/** A supervisor's credentials typed at the counter (ADR 0009), while the switch is on. */
export interface ApproverState {
  enabled: boolean;
  username: string;
  password: string;
}

export const NO_APPROVER: ApproverState = { enabled: false, username: "", password: "" };

/** The approver to send: credentials when switched on and filled, else none. */
export function approverPayload(state: ApproverState): { username: string; password: string } | null {
  if (!state.enabled || !state.username.trim() || !state.password) return null;
  return { username: state.username.trim(), password: state.password };
}
