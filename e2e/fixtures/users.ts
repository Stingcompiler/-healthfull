/**
 * E2E seed users, one per role. Created (and reset) by
 * `backend/apps/core/management/commands/seed_e2e.py`; keep both files in sync.
 *
 * TEST VALUES ONLY. These accounts exist only in the throwaway e2e database
 * (e2e_hospital_<hash>) that scripts/e2e.sh drops and recreates on every run.
 * The password is recorded here and in seed_e2e.py and nowhere else.
 */
export const E2E_PASSWORD = "Test-Pass-2026";

/**
 * The password the forced-change spec sets (TEST VALUE). `reseed()` puts the seed
 * password back afterwards, so it only ever exists for a moment in the e2e DB.
 */
export const E2E_CHANGED_PASSWORD = "Changed-Pass-2026-e2e";

export const ROLE_CODES = [
  "receptionist",
  "doctor",
  "cashier",
  "cashier_supervisor",
  "pharmacist",
  "lab_tech",
  "lab_supervisor",
  "nurse",
  "accountant",
  "manager",
  "admin",
] as const;
export type RoleCode = (typeof ROLE_CODES)[number];

export interface E2EUser {
  username: string;
  role: RoleCode;
  fullNameAr: string;
  fullNameEn: string;
}

export const USERS = {
  reception: { username: "reception", role: "receptionist", fullNameAr: "سارة عبدالله", fullNameEn: "Sara Abdalla" },
  doctor: { username: "doctor", role: "doctor", fullNameAr: "د. أحمد الطيب", fullNameEn: "Dr. Ahmed Altayeb" },
  cashier: { username: "cashier", role: "cashier", fullNameAr: "محمد عثمان", fullNameEn: "Mohamed Osman" },
  cashsup: { username: "cashsup", role: "cashier_supervisor", fullNameAr: "هالة إبراهيم", fullNameEn: "Hala Ibrahim" },
  pharmacist: { username: "pharmacist", role: "pharmacist", fullNameAr: "عمر الفاتح", fullNameEn: "Omer Alfatih" },
  labtech: { username: "labtech", role: "lab_tech", fullNameAr: "منى حسن", fullNameEn: "Muna Hassan" },
  labsup: { username: "labsup", role: "lab_supervisor", fullNameAr: "خالد بشير", fullNameEn: "Khalid Bashir" },
  nurse: { username: "nurse", role: "nurse", fullNameAr: "آمنة يوسف", fullNameEn: "Amna Yousif" },
  accountant: { username: "accountant", role: "accountant", fullNameAr: "طارق الأمين", fullNameEn: "Tarig Alamin" },
  manager: { username: "manager", role: "manager", fullNameAr: "نادية محمود", fullNameEn: "Nadia Mahmoud" },
  admin: { username: "admin", role: "admin", fullNameAr: "مدير النظام", fullNameEn: "System Admin" },
} as const satisfies Record<string, E2EUser>;

/** Seed user key, e.g. "cashier". `login(page, "cashier")`. */
export type UserKey = keyof typeof USERS;

/** Accepts a seed user key ("cashsup") or a role code ("cashier_supervisor"). */
export function resolveUser(who: UserKey | RoleCode): E2EUser {
  if (who in USERS) return USERS[who as UserKey];
  const byRole = Object.values(USERS).find((user) => user.role === who);
  if (!byRole) throw new Error(`No e2e seed user for "${who}"`);
  return byRole;
}
