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
  "display",
] as const;
export type RoleCode = (typeof ROLE_CODES)[number];

export interface E2EUser {
  username: string;
  role: RoleCode;
  fullNameAr: string;
  fullNameEn: string;
}

export const USERS = {
  reception: {
    username: "reception",
    role: "receptionist",
    fullNameAr: "سارة عبدالله",
    fullNameEn: "Sara Abdalla",
  },
  doctor: {
    username: "doctor",
    role: "doctor",
    fullNameAr: "د. أحمد الطيب",
    fullNameEn: "Dr. Ahmed Altayeb",
  },
  cashier: {
    username: "cashier",
    role: "cashier",
    fullNameAr: "محمد عثمان",
    fullNameEn: "Mohamed Osman",
  },
  cashsup: {
    username: "cashsup",
    role: "cashier_supervisor",
    fullNameAr: "هالة إبراهيم",
    fullNameEn: "Hala Ibrahim",
  },
  pharmacist: {
    username: "pharmacist",
    role: "pharmacist",
    fullNameAr: "عمر الفاتح",
    fullNameEn: "Omer Alfatih",
  },
  labtech: {
    username: "labtech",
    role: "lab_tech",
    fullNameAr: "منى حسن",
    fullNameEn: "Muna Hassan",
  },
  labsup: {
    username: "labsup",
    role: "lab_supervisor",
    fullNameAr: "خالد بشير",
    fullNameEn: "Khalid Bashir",
  },
  nurse: {
    username: "nurse",
    role: "nurse",
    fullNameAr: "آمنة يوسف",
    fullNameEn: "Amna Yousif",
  },
  accountant: {
    username: "accountant",
    role: "accountant",
    fullNameAr: "طارق الأمين",
    fullNameEn: "Tarig Alamin",
  },
  manager: {
    username: "manager",
    role: "manager",
    fullNameAr: "نادية محمود",
    fullNameEn: "Nadia Mahmoud",
  },
  admin: {
    username: "admin",
    role: "admin",
    fullNameAr: "مدير النظام",
    fullNameEn: "System Admin",
  },
  // The waiting-room kiosk account (ADR 0019): /display/queue and nothing else.
  display: {
    username: "display",
    role: "display",
    fullNameAr: "شاشة الانتظار",
    fullNameEn: "Waiting-room screen",
  },
} as const satisfies Record<string, E2EUser>;

/**
 * More doctor accounts (role `doctor`, same E2E_PASSWORD) seeded with the base catalog, one per
 * clinic department besides general practice. Each has a schedule and a consultation fee
 * service (backend/apps/core/e2e/catalog.py, EXTRA_DOCTORS). `USERS.doctor` is the general
 * practitioner (department GEN, CONS-GEN).
 */
export const EXTRA_DOCTORS = {
  pediatrician: {
    username: "pediatrician",
    role: "doctor",
    fullNameAr: "د. فاطمة الزين",
    fullNameEn: "Dr. Fatima Alzain",
  },
  gynecologist: {
    username: "gynecologist",
    role: "doctor",
    fullNameAr: "د. سلمى عوض",
    fullNameEn: "Dr. Salma Awad",
  },
  dentist: {
    username: "dentist",
    role: "doctor",
    fullNameAr: "د. ياسر النور",
    fullNameEn: "Dr. Yasir Alnour",
  },
} as const satisfies Record<string, E2EUser>;

/** Department code of each seeded doctor (USERS.doctor and EXTRA_DOCTORS). */
export const DOCTOR_DEPARTMENTS = {
  doctor: "GEN",
  pediatrician: "PED",
  gynecologist: "GYN",
  dentist: "DEN",
} as const;

/**
 * Break-glass superuser seeded apart from the role users (`root`, no role, every registered
 * permission through is_superuser). The `admin` user above is a normal user holding the admin
 * role, so specs exercise that role's real permissions. Use root only to test the superuser.
 */
export const SUPERUSER = {
  username: "root",
  fullNameAr: "حساب الطوارئ",
  fullNameEn: "Break-glass superuser",
} as const;

/** Seed user key, e.g. "cashier". `login(page, "cashier")`. */
export type UserKey = keyof typeof USERS;

/** One of the extra doctor accounts, e.g. "pediatrician". */
export type ExtraDoctorKey = keyof typeof EXTRA_DOCTORS;

/** Any seeded login: a role user key, an extra doctor or a role code. */
export type SeedUser = UserKey | ExtraDoctorKey | RoleCode;

/**
 * Accepts a seed user key ("cashsup"), an extra doctor ("pediatrician") or a role code
 * ("cashier_supervisor"; a role code means the role user, so "doctor" is USERS.doctor).
 */
export function resolveUser(who: SeedUser): E2EUser {
  if (who in USERS) return USERS[who as UserKey];
  if (who in EXTRA_DOCTORS) return EXTRA_DOCTORS[who as ExtraDoctorKey];
  const byRole = Object.values(USERS).find((user) => user.role === who);
  if (!byRole) throw new Error(`No e2e seed user for "${who}"`);
  return byRole;
}
