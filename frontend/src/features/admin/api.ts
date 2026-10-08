/**
 * TanStack Query hooks for the administration screens (ARCHITECTURE 5.5).
 * Every call goes through the typed openapi-fetch client; components never
 * build URLs or compute money.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { authKeys } from "@/lib/auth/api";

import type {
  BulkUpdateIn,
  CenterProfileIn,
  CoveragePreviewIn,
  CoverageRuleIn,
  CoverageRulePatch,
  DepartmentIn,
  DepartmentPatch,
  DoctorIn,
  DoctorPatch,
  ExclusionIn,
  MatrixChangeIn,
  PayerIn,
  PayerPatch,
  PolicyIn,
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
  policy: ["admin", "policy"] as const,
  departments: ["admin", "departments"] as const,
  rooms: ["admin", "rooms"] as const,
  doctors: ["admin", "doctors"] as const,
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
  return useAdminMutation((body: CenterProfileIn) => unwrap(api.PUT("/api/core/center", { body })), [adminKeys.center]);
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
    [adminKeys.center],
  );
}

export function useDeleteLogo() {
  return useAdminMutation(() => unwrap(api.DELETE("/api/core/center/logo")), [adminKeys.center]);
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
