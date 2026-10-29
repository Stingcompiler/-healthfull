/**
 * TanStack Query hooks for the administration screens (ARCHITECTURE 5.5).
 * Every call goes through the typed openapi-fetch client; components never
 * build URLs or compute money.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { authKeys } from "@/lib/auth/api";
import { centerIdentityKey, centerPageKey } from "@/lib/center/api";
import { setSiteConfig, getSiteConfig } from "@/lib/site";

import type {
  AnnouncementIn,
  AnnouncementPatch,
  BulkUpdateIn,
  CenterFaqIn,
  CenterFaqPatch,
  CenterMediaPatch,
  CenterPageIn,
  CenterProfileIn,
  DoctorSiteProfilePatch,
  MediaKind,
  TestimonialIn,
  TestimonialPatch,
  CoveragePreviewIn,
  CoverageRuleIn,
  CoverageRulePatch,
  BankIn,
  BankPatch,
  DepartmentIn,
  DepartmentPatch,
  DoctorIn,
  DoctorPatch,
  ExclusionIn,
  MatrixChangeIn,
  PayerIn,
  PayerPatch,
  PolicyIn,
  PublicSiteSettingsIn,
  PriceChangeIn,
  PriceListIn,
  PrintTemplateIn,
  PrintTemplateOut,
  ReasonCategory,
  ReasonCodeIn,
  ReasonCodePatch,
  RoomIn,
  RoomPatch,
  ScheduleSessionIn,
  ServiceIn,
  ServiceKind,
  ServicePatch,
  UserIn,
  UserPatch,
  VersionIn,
} from "./types";

export const adminKeys = {
  all: ["admin"] as const,
  users: (params?: object) => ["admin", "users", params ?? {}] as const,
  roles: ["admin", "roles"] as const,
  matrix: ["admin", "matrix"] as const,
  center: ["admin", "center"] as const,
  centerPage: ["admin", "center-page"] as const,
  announcements: ["admin", "announcements"] as const,
  centerMedia: ["admin", "center-media"] as const,
  centerFaq: ["admin", "center-faq"] as const,
  testimonials: ["admin", "testimonials"] as const,
  doctorSite: ["admin", "doctor-site"] as const,
  sitePayers: ["admin", "site-payers"] as const,
  siteServices: ["admin", "site-services"] as const,
  policy: ["admin", "policy"] as const,
  publicSite: ["admin", "public-site"] as const,
  departments: ["admin", "departments"] as const,
  banks: ["admin", "banks"] as const,
  rooms: ["admin", "rooms"] as const,
  doctors: ["admin", "doctors"] as const,
  doctorCandidates: ["admin", "doctors", "candidates"] as const,
  reasons: ["admin", "reasons"] as const,
  sequences: (year?: number) => ["admin", "sequences", year ?? 0] as const,
  printTemplates: ["admin", "print-templates"] as const,
  services: (params?: object) => ["admin", "services", params ?? {}] as const,
  categories: ["admin", "categories"] as const,
  priceLists: ["admin", "price-lists"] as const,
  priceList: (id: number) => ["admin", "price-lists", id] as const,
  priceItems: (versionId: number, params?: object) => ["admin", "price-items", versionId, params ?? {}] as const,
  payers: (params?: object) => ["admin", "payers", params ?? {}] as const,
  payer: (id: number) => ["admin", "payer", id] as const,
  coveragePreview: (body: object) => ["admin", "coverage-preview", body] as const,
};

/** A mutation that refreshes the given query key prefixes once it succeeds. */
function useAdminMutation<TVars, TData>(fn: (vars: TVars) => Promise<TData>, invalidate: readonly QueryKey[]) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      await Promise.all(invalidate.map((queryKey) => queryClient.invalidateQueries({ queryKey })));
    },
  });
}

// --- Users and roles ------------------------------------------------------------------------

export interface UserFilters {
  q?: string;
  role?: UserIn["roles"][number];
  active?: boolean;
}

export function useUsers(filters: UserFilters) {
  return useQuery({
    queryKey: adminKeys.users(filters),
    queryFn: () => unwrap(api.GET("/api/core/users", { params: { query: { ...filters, page_size: 100 } } })),
    placeholderData: keepPreviousData,
  });
}

export function useRoles() {
  return useQuery({ queryKey: adminKeys.roles, queryFn: () => unwrap(api.GET("/api/core/roles")) });
}

const USER_KEYS = [["admin", "users"], adminKeys.roles] as const;

export function useCreateUser() {
  return useAdminMutation((body: UserIn) => unwrap(api.POST("/api/core/users", { body })), USER_KEYS);
}

export function useUpdateUser() {
  return useAdminMutation(
    ({ id, body }: { id: number; body: UserPatch }) =>
      unwrap(api.PATCH("/api/core/users/{user_id}", { params: { path: { user_id: id } }, body })),
    [...USER_KEYS, adminKeys.doctors],
  );
}

export function useResetPassword() {
  return useAdminMutation(
    ({ id, newPassword }: { id: number; newPassword: string }) =>
      unwrap(
        api.POST("/api/core/users/{user_id}/reset-password", {
          params: { path: { user_id: id } },
          body: { new_password: newPassword },
        }),
      ),
    USER_KEYS,
  );
}

export function useUnlockUser() {
  return useAdminMutation(
    ({ id, reason }: { id: number; reason: string }) =>
      unwrap(api.POST("/api/core/users/{user_id}/unlock", { params: { path: { user_id: id } }, body: { reason } })),
    USER_KEYS,
  );
}

export function usePermissionMatrix() {
  return useQuery({ queryKey: adminKeys.matrix, queryFn: () => unwrap(api.GET("/api/core/permissions/matrix")) });
}

export function useUpdateMatrix() {
  return useAdminMutation(
    ({ changes, reason }: { changes: MatrixChangeIn[]; reason: string }) =>
      unwrap(api.PUT("/api/core/permissions/matrix", { body: { changes, reason } })),
    // The editor's own permissions may have changed.
    [adminKeys.matrix, authKeys.me],
  );
}

// --- Center, policy, numbering, print templates ---------------------------------------------

export function useCenterProfile() {
  return useQuery({ queryKey: adminKeys.center, queryFn: () => unwrap(api.GET("/api/core/center")) });
}

export function useUpdateCenterProfile() {
  return useAdminMutation(
    (body: CenterProfileIn) => unwrap(api.PUT("/api/core/center", { body })),
    [adminKeys.center, centerIdentityKey],
  );
}

export function useUploadLogo() {
  return useAdminMutation(
    (file: File) =>
      unwrap(
        api.POST("/api/core/center/logo", {
          body: { file: file as unknown as string },
          bodySerializer: (body) => {
            const form = new FormData();
            form.append("file", body.file as unknown as Blob);
            return form;
          },
        }),
      ),
    [adminKeys.center, centerIdentityKey],
  );
}

export function useDeleteLogo() {
  return useAdminMutation(() => unwrap(api.DELETE("/api/core/center/logo")), [adminKeys.center, centerIdentityKey]);
}

// --- Public center page (portal) ----------------------------------------------------------

export function useCenterPageSettings() {
  return useQuery({ queryKey: adminKeys.centerPage, queryFn: () => unwrap(api.GET("/api/core/center-page")) });
}

export function useUpdateCenterPage() {
  return useAdminMutation(
    (body: CenterPageIn) => unwrap(api.PUT("/api/core/center-page", { body })),
    // The public page itself is cached under its own key.
    [adminKeys.centerPage, centerPageKey],
  );
}

export function useAnnouncements() {
  return useQuery({ queryKey: adminKeys.announcements, queryFn: () => unwrap(api.GET("/api/core/announcements")) });
}

export function useSaveAnnouncement() {
  return useAdminMutation(
    ({ id, body }: { id?: number; body: AnnouncementIn | AnnouncementPatch }) =>
      id === undefined
        ? unwrap(api.POST("/api/core/announcements", { body: body as AnnouncementIn }))
        : unwrap(
            api.PATCH("/api/core/announcements/{announcement_id}", {
              params: { path: { announcement_id: id } },
              body,
            }),
          ),
    [adminKeys.announcements, centerPageKey],
  );
}

// --- Website content (ADR 0029 H) ----------------------------------------------------------

export function useCenterMedia() {
  return useQuery({ queryKey: adminKeys.centerMedia, queryFn: () => unwrap(api.GET("/api/core/center-media")) });
}

export function useUploadCenterMedia() {
  return useAdminMutation(
    ({ file, kind, alt_ar, alt_en }: { file: File; kind: MediaKind; alt_ar: string; alt_en: string }) =>
      unwrap(
        api.POST("/api/core/center-media", {
          body: { file: file as unknown as string, kind, alt_ar, alt_en },
          bodySerializer: (body) => {
            const form = new FormData();
            form.append("file", body.file as unknown as Blob);
            form.append("kind", body.kind);
            form.append("alt_ar", body.alt_ar ?? "");
            form.append("alt_en", body.alt_en ?? "");
            return form;
          },
        }),
      ),
    [adminKeys.centerMedia, centerPageKey],
  );
}

export function useUpdateCenterMedia() {
  return useAdminMutation(
    ({ id, body }: { id: number; body: CenterMediaPatch }) =>
      unwrap(api.PATCH("/api/core/center-media/{media_id}", { params: { path: { media_id: id } }, body })),
    [adminKeys.centerMedia, centerPageKey],
  );
}

export function useDeleteCenterMedia() {
  return useAdminMutation(
    (id: number) => unwrap(api.DELETE("/api/core/center-media/{media_id}", { params: { path: { media_id: id } } })),
    [adminKeys.centerMedia, adminKeys.doctorSite, centerPageKey],
  );
}

export function useCenterFaq() {
  return useQuery({ queryKey: adminKeys.centerFaq, queryFn: () => unwrap(api.GET("/api/core/center-faq")) });
}

export function useSaveCenterFaq() {
  return useAdminMutation(
    ({ id, body }: { id?: number; body: CenterFaqIn | CenterFaqPatch }) =>
      id === undefined
        ? unwrap(api.POST("/api/core/center-faq", { body: body as CenterFaqIn }))
        : unwrap(api.PATCH("/api/core/center-faq/{faq_id}", { params: { path: { faq_id: id } }, body })),
    [adminKeys.centerFaq, centerPageKey],
  );
}

export function useDeleteCenterFaq() {
  return useAdminMutation(
    (id: number) => unwrap(api.DELETE("/api/core/center-faq/{faq_id}", { params: { path: { faq_id: id } } })),
    [adminKeys.centerFaq, centerPageKey],
  );
}

export function useTestimonials() {
  return useQuery({ queryKey: adminKeys.testimonials, queryFn: () => unwrap(api.GET("/api/core/testimonials")) });
}

export function useSaveTestimonial() {
  return useAdminMutation(
    ({ id, body }: { id?: number; body: TestimonialIn | TestimonialPatch }) =>
      id === undefined
        ? unwrap(api.POST("/api/core/testimonials", { body: body as TestimonialIn }))
        : unwrap(
            api.PATCH("/api/core/testimonials/{testimonial_id}", {
              params: { path: { testimonial_id: id } },
              body,
            }),
          ),
    [adminKeys.testimonials, centerPageKey],
  );
}

export function useApproveTestimonial() {
  return useAdminMutation(
    (id: number) =>
      unwrap(api.POST("/api/core/testimonials/{testimonial_id}/approve", { params: { path: { testimonial_id: id } } })),
    [adminKeys.testimonials, centerPageKey],
  );
}

export function useDeleteTestimonial() {
  return useAdminMutation(
    (id: number) =>
      unwrap(api.DELETE("/api/core/testimonials/{testimonial_id}", { params: { path: { testimonial_id: id } } })),
    [adminKeys.testimonials, centerPageKey],
  );
}

export function useDoctorSiteProfiles() {
  return useQuery({
    queryKey: adminKeys.doctorSite,
    queryFn: () => unwrap(api.GET("/api/core/center-page/doctors")),
  });
}

export function useUpdateDoctorSiteProfile() {
  return useAdminMutation(
    ({ id, body }: { id: number; body: DoctorSiteProfilePatch }) =>
      unwrap(api.PATCH("/api/core/center-page/doctors/{doctor_id}", { params: { path: { doctor_id: id } }, body })),
    [adminKeys.doctorSite, centerPageKey],
  );
}

export function useSitePayers() {
  return useQuery({ queryKey: adminKeys.sitePayers, queryFn: () => unwrap(api.GET("/api/core/center-page/payers")) });
}

export function useSetPayerOnSite() {
  return useAdminMutation(
    ({ id, show }: { id: number; show: boolean }) =>
      unwrap(
        api.PUT("/api/core/center-page/payers/{payer_id}", {
          params: { path: { payer_id: id } },
          body: { show_on_site: show },
        }),
      ),
    [adminKeys.sitePayers, centerPageKey],
  );
}

export function useSiteServices() {
  return useQuery({
    queryKey: adminKeys.siteServices,
    queryFn: () => unwrap(api.GET("/api/core/center-page/services")),
  });
}

export function useSetServiceOnSite() {
  return useAdminMutation(
    ({ id, show }: { id: number; show: boolean }) =>
      unwrap(
        api.PUT("/api/core/center-page/services/{service_id}", {
          params: { path: { service_id: id } },
          body: { show_on_site: show },
        }),
      ),
    [adminKeys.siteServices, centerPageKey],
  );
}

// --- Public site switches and online booking rules (ADR 0028, 0029) -----------------------

export function usePublicSiteSettings() {
  return useQuery({ queryKey: adminKeys.publicSite, queryFn: () => unwrap(api.GET("/api/core/public-site")) });
}

export function useUpdatePublicSiteSettings() {
  return useAdminMutation(
    async (body: PublicSiteSettingsIn) => {
      const saved = await unwrap(api.PUT("/api/core/public-site", { body }));
      // The switches the SPA read at start follow the save in this tab; other tabs on reload.
      setSiteConfig({
        ...getSiteConfig(),
        centerSite: saved.site_enabled,
        onlineBooking: saved.online_booking_enabled,
        patientTracking: saved.patient_tracking_enabled,
      });
      return saved;
    },
    [adminKeys.publicSite, centerPageKey],
  );
}

export function usePolicy() {
  return useQuery({ queryKey: adminKeys.policy, queryFn: () => unwrap(api.GET("/api/core/policy")) });
}

export function useUpdatePolicy() {
  return useAdminMutation((body: PolicyIn) => unwrap(api.PUT("/api/core/policy", { body })), [adminKeys.policy]);
}

export function useSequences(year?: number) {
  return useQuery({
    queryKey: adminKeys.sequences(year),
    queryFn: () => unwrap(api.GET("/api/core/sequences", { params: { query: year ? { year } : {} } })),
    placeholderData: keepPreviousData,
  });
}

export function usePrintTemplates() {
  return useQuery({ queryKey: adminKeys.printTemplates, queryFn: () => unwrap(api.GET("/api/core/print-templates")) });
}

export function useSavePrintTemplate() {
  return useAdminMutation(
    ({
      document,
      paper,
      body,
    }: {
      document: PrintTemplateOut["document"];
      paper: PrintTemplateOut["paper"];
      body: PrintTemplateIn;
    }) =>
      unwrap(api.PUT("/api/core/print-templates/{document}/{paper}", { params: { path: { document, paper } }, body })),
    [adminKeys.printTemplates],
  );
}

// --- Departments, rooms, doctors --------------------------------------------------------------

export function useDepartments() {
  return useQuery({ queryKey: adminKeys.departments, queryFn: () => unwrap(api.GET("/api/core/departments")) });
}

export function useSaveDepartment() {
  return useAdminMutation(
    ({ id, body }: { id?: number; body: DepartmentIn | DepartmentPatch }) =>
      id === undefined
        ? unwrap(api.POST("/api/core/departments", { body: body as DepartmentIn }))
        : unwrap(api.PATCH("/api/core/departments/{department_id}", { params: { path: { department_id: id } }, body })),
    [adminKeys.departments],
  );
}

export function useBanks() {
  return useQuery({ queryKey: adminKeys.banks, queryFn: () => unwrap(api.GET("/api/payments/banks/all")) });
}

export function useSaveBank() {
  return useAdminMutation(
    ({ id, body }: { id?: number; body: BankIn | BankPatch }) =>
      id === undefined
        ? unwrap(api.POST("/api/payments/banks", { body: body as BankIn }))
        : unwrap(api.PATCH("/api/payments/banks/{bank_id}", { params: { path: { bank_id: id } }, body })),
    [adminKeys.banks],
  );
}

export function useRooms() {
  return useQuery({ queryKey: adminKeys.rooms, queryFn: () => unwrap(api.GET("/api/core/rooms")) });
}

export function useSaveRoom() {
  return useAdminMutation(
    ({ id, body }: { id?: number; body: RoomIn | RoomPatch }) =>
      id === undefined
        ? unwrap(api.POST("/api/core/rooms", { body: body as RoomIn }))
        : unwrap(api.PATCH("/api/core/rooms/{room_id}", { params: { path: { room_id: id } }, body })),
    [adminKeys.rooms, adminKeys.departments],
  );
}

export function useDoctors() {
  return useQuery({ queryKey: adminKeys.doctors, queryFn: () => unwrap(api.GET("/api/core/doctors")) });
}

/** Doctor-role users without a profile yet (needs only core.manage_departments). */
export function useDoctorCandidates() {
  return useQuery({
    queryKey: adminKeys.doctorCandidates,
    queryFn: () => unwrap(api.GET("/api/core/doctors/candidates")),
  });
}

export function useSaveDoctor() {
  return useAdminMutation(
    ({ id, body }: { id?: number; body: DoctorIn | DoctorPatch }) =>
      id === undefined
        ? unwrap(api.POST("/api/core/doctors", { body: body as DoctorIn }))
        : unwrap(api.PATCH("/api/core/doctors/{doctor_id}", { params: { path: { doctor_id: id } }, body })),
    [adminKeys.doctors, adminKeys.departments, ["admin", "users"]],
  );
}

export function useSetSchedule() {
  return useAdminMutation(
    ({ id, sessions }: { id: number; sessions: ScheduleSessionIn[] }) =>
      unwrap(
        api.PUT("/api/core/doctors/{doctor_id}/schedule", { params: { path: { doctor_id: id } }, body: { sessions } }),
      ),
    [adminKeys.doctors],
  );
}

// --- Doctor time off (ADR 0029 C) -----------------------------------------------------------

const timeOffKey = (doctorId: number) => ["admin", "time-off", doctorId] as const;

export function useTimeOff(doctorId: number) {
  return useQuery({
    queryKey: timeOffKey(doctorId),
    queryFn: () =>
      unwrap(api.GET("/api/visits/doctors/{doctor_id}/time-off", { params: { path: { doctor_id: doctorId } } })),
  });
}

export function useAddTimeOff(doctorId: number) {
  return useAdminMutation(
    (body: { starts_at: string; ends_at: string; reason_ar: string; reason_en: string }) =>
      unwrap(api.POST("/api/visits/doctors/{doctor_id}/time-off", { params: { path: { doctor_id: doctorId } }, body })),
    [timeOffKey(doctorId)],
  );
}

export function useRemoveTimeOff(doctorId: number) {
  return useAdminMutation(
    (id: number) => unwrap(api.DELETE("/api/visits/time-off/{time_off_id}", { params: { path: { time_off_id: id } } })),
    [timeOffKey(doctorId)],
  );
}

// --- Reason codes -----------------------------------------------------------------------------

export function useReasonCodes(category?: ReasonCategory) {
  return useQuery({
    queryKey: [...adminKeys.reasons, category ?? "all"],
    queryFn: () => unwrap(api.GET("/api/core/reason-codes", { params: { query: category ? { category } : {} } })),
  });
}

export function useSaveReasonCode() {
  return useAdminMutation(
    ({ id, body }: { id?: number; body: ReasonCodeIn | ReasonCodePatch }) =>
      id === undefined
        ? unwrap(api.POST("/api/core/reason-codes", { body: body as ReasonCodeIn }))
        : unwrap(api.PATCH("/api/core/reason-codes/{reason_id}", { params: { path: { reason_id: id } }, body })),
    [adminKeys.reasons],
  );
}

// --- Services and categories ----------------------------------------------------------------

export interface ServiceFilters {
  q?: string;
  kind?: ServiceKind;
  department_id?: number;
  active?: boolean;
}

export function useServices(filters: ServiceFilters, enabled = true) {
  return useQuery({
    queryKey: adminKeys.services(filters),
    queryFn: () => unwrap(api.GET("/api/catalog/services", { params: { query: { ...filters, page_size: 100 } } })),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useSaveService() {
  return useAdminMutation(
    ({ id, body }: { id?: number; body: ServiceIn | ServicePatch }) =>
      id === undefined
        ? unwrap(api.POST("/api/catalog/services", { body: body as ServiceIn }))
        : unwrap(api.PATCH("/api/catalog/services/{service_id}", { params: { path: { service_id: id } }, body })),
    [["admin", "services"]],
  );
}

export function useCategories() {
  return useQuery({ queryKey: adminKeys.categories, queryFn: () => unwrap(api.GET("/api/catalog/categories")) });
}

// --- Price lists and versions -----------------------------------------------------------------

export function usePriceLists() {
  return useQuery({ queryKey: adminKeys.priceLists, queryFn: () => unwrap(api.GET("/api/catalog/price-lists")) });
}

export function usePriceList(id: number) {
  return useQuery({
    queryKey: adminKeys.priceList(id),
    queryFn: () =>
      unwrap(api.GET("/api/catalog/price-lists/{price_list_id}", { params: { path: { price_list_id: id } } })),
  });
}

const PRICE_KEYS = [adminKeys.priceLists, ["admin", "price-items"]] as const;

export function useCreatePriceList() {
  return useAdminMutation((body: PriceListIn) => unwrap(api.POST("/api/catalog/price-lists", { body })), PRICE_KEYS);
}

export function useUpdatePriceList() {
  return useAdminMutation(
    ({ id, active }: { id: number; active: boolean }) =>
      unwrap(
        api.PATCH("/api/catalog/price-lists/{price_list_id}", {
          params: { path: { price_list_id: id } },
          body: { active },
        }),
      ),
    PRICE_KEYS,
  );
}

export function useCreateVersion() {
  return useAdminMutation(
    ({ priceListId, body }: { priceListId: number; body: VersionIn }) =>
      unwrap(
        api.POST("/api/catalog/price-lists/{price_list_id}/versions", {
          params: { path: { price_list_id: priceListId } },
          body,
        }),
      ),
    PRICE_KEYS,
  );
}

export function useWithdrawVersion() {
  return useAdminMutation(
    ({ versionId, reason }: { versionId: number; reason: string }) =>
      unwrap(
        api.POST("/api/catalog/versions/{version_id}/withdraw", {
          params: { path: { version_id: versionId } },
          body: { reason },
        }),
      ),
    PRICE_KEYS,
  );
}

export interface PriceItemFilters {
  q?: string;
  kind?: ServiceKind;
}

export function usePriceItems(versionId: number | null, filters: PriceItemFilters) {
  return useQuery({
    queryKey: adminKeys.priceItems(versionId ?? 0, filters),
    queryFn: () =>
      unwrap(
        api.GET("/api/catalog/versions/{version_id}/items", {
          params: { path: { version_id: versionId ?? 0 }, query: { ...filters, page_size: 100 } },
        }),
      ),
    enabled: versionId !== null,
    placeholderData: keepPreviousData,
  });
}

export function useSetPriceItems() {
  return useAdminMutation(
    ({ versionId, items }: { versionId: number; items: PriceChangeIn[] }) =>
      unwrap(
        api.PUT("/api/catalog/versions/{version_id}/items", {
          params: { path: { version_id: versionId } },
          body: { items },
        }),
      ),
    PRICE_KEYS,
  );
}

export function useBulkPreview() {
  return useMutation({
    mutationFn: ({ priceListId, body }: { priceListId: number; body: BulkUpdateIn }) =>
      unwrap(
        api.POST("/api/catalog/price-lists/{price_list_id}/bulk-preview", {
          params: { path: { price_list_id: priceListId } },
          body,
        }),
      ),
  });
}

export function useApplyBulk() {
  return useAdminMutation(
    ({ priceListId, body }: { priceListId: number; body: BulkUpdateIn }) =>
      unwrap(
        api.POST("/api/catalog/price-lists/{price_list_id}/bulk-update", {
          params: { path: { price_list_id: priceListId } },
          body,
        }),
      ),
    PRICE_KEYS,
  );
}

// --- Payers, coverage rules, exclusions -------------------------------------------------------

export function usePayers(q?: string) {
  return useQuery({
    queryKey: adminKeys.payers({ q }),
    queryFn: () => unwrap(api.GET("/api/catalog/payers", { params: { query: { q, page_size: 100 } } })),
    placeholderData: keepPreviousData,
  });
}

export function usePayer(id: number) {
  return useQuery({
    queryKey: adminKeys.payer(id),
    queryFn: () => unwrap(api.GET("/api/catalog/payers/{payer_id}", { params: { path: { payer_id: id } } })),
  });
}

const PAYER_KEYS = [["admin", "payers"], ["admin", "payer"], adminKeys.priceLists] as const;

export function useSavePayer() {
  return useAdminMutation(
    ({ id, body }: { id?: number; body: PayerIn | PayerPatch }) =>
      id === undefined
        ? unwrap(api.POST("/api/catalog/payers", { body: body as PayerIn }))
        : unwrap(api.PATCH("/api/catalog/payers/{payer_id}", { params: { path: { payer_id: id } }, body })),
    PAYER_KEYS,
  );
}

export function useSaveRule() {
  return useAdminMutation(
    ({ payerId, id, body }: { payerId: number; id?: number; body: CoverageRuleIn | CoverageRulePatch }) =>
      id === undefined
        ? unwrap(
            api.POST("/api/catalog/payers/{payer_id}/rules", {
              params: { path: { payer_id: payerId } },
              body: body as CoverageRuleIn,
            }),
          )
        : unwrap(api.PATCH("/api/catalog/rules/{rule_id}", { params: { path: { rule_id: id } }, body })),
    PAYER_KEYS,
  );
}

export function useSaveExclusion() {
  return useAdminMutation(
    ({ payerId, id, body }: { payerId: number; id?: number; body: ExclusionIn | { active: boolean } }) =>
      id === undefined
        ? unwrap(
            api.POST("/api/catalog/payers/{payer_id}/exclusions", {
              params: { path: { payer_id: payerId } },
              body: body as ExclusionIn,
            }),
          )
        : unwrap(api.PATCH("/api/catalog/exclusions/{exclusion_id}", { params: { path: { exclusion_id: id } }, body })),
    PAYER_KEYS,
  );
}

/** The live example split of a rule being edited, computed by the backend's coverage rule. */
export function useCoveragePreview(body: CoveragePreviewIn | null) {
  return useQuery({
    queryKey: adminKeys.coveragePreview(body ?? {}),
    queryFn: () => {
      if (body === null) throw new Error("coverage preview without a rule");
      return unwrap(api.POST("/api/catalog/coverage/preview", { body }));
    },
    enabled: body !== null,
    placeholderData: keepPreviousData,
    retry: false,
  });
}
