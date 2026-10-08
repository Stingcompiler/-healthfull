import { zodResolver } from "@hookform/resolvers/zod";
import type { ColumnDef } from "@tanstack/react-table";
import { KeyRound, LockOpen, Pencil, Plus, UserCheck, UserX } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { DataTable } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { PasswordField, SwitchField, TextareaField, TextField } from "@/components/form";
import { SearchInput } from "@/components/SearchInput";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ROLES } from "@/lib/auth/permissions";
import { useCurrentUser } from "@/lib/auth/hooks";
import { useTranslateError } from "@/lib/api/translate-error";
import { vmsg } from "@/lib/validation";

import { useCreateUser, useResetPassword, useUnlockUser, useUpdateUser, useUsers, type UserFilters } from "../api";
import { AdminPage, QueryState } from "../components/AdminPage";
import { FilterBar, FilterSelect } from "../components/Filters";
import { ActiveBadge, Code, FormDialog } from "../components/FormDialog";
import { RolesField } from "../components/RolesField";
import type { RoleCode, UserOut } from "../types";

const PASSWORD_MIN = 8;
const password = z
  .string()
  .min(PASSWORD_MIN, vmsg("validation.minLength", { count: PASSWORD_MIN }))
  .refine((v) => !/^\d+$/.test(v), vmsg("validation.passwordNumeric"));
const roles = z.array(z.enum(ROLES)).min(1, vmsg("admin:users.rolesRequired"));
const names = {
  full_name_ar: z.string().max(150),
  full_name_en: z.string().max(150),
  phone: z.string().max(30),
};

const createSchema = z.object({
  username: z
    .string()
    .min(1, vmsg("validation.required"))
    .max(150)
    .regex(/^[\w.@+-]+$/, vmsg("admin:users.usernameRule")),
  ...names,
  roles,
  password,
});
type CreateValues = z.infer<typeof createSchema>;

const editSchema = z.object({ ...names, roles, is_active: z.boolean() });
type EditValues = z.infer<typeof editSchema>;

const resetSchema = z.object({ password });
type ResetValues = z.infer<typeof resetSchema>;

const unlockSchema = z.object({ reason: z.string().trim().min(1, vmsg("validation.required")).max(500) });
type UnlockValues = z.infer<typeof unlockSchema>;

type Dialog = { kind: "create" } | { kind: "edit" | "reset" | "unlock"; user: UserOut } | null;

function displayName(user: UserOut, language: string): string {
  const name = language === "ar" ? user.full_name_ar || user.full_name_en : user.full_name_en || user.full_name_ar;
  return name || user.username;
}

export function UsersPage() {
  const { t, i18n } = useTranslation(["admin", "common"]);
  const [filters, setFilters] = useState<UserFilters>({});
  const [dialog, setDialog] = useState<Dialog>(null);
  const users = useUsers(filters);
  const update = useUpdateUser();
  const me = useCurrentUser();
  const translateError = useTranslateError();

  const setActive = async (user: UserOut, active: boolean) => {
    try {
      await update.mutateAsync({ id: user.id, body: { is_active: active } });
      toast.success(active ? t("admin:users.activated") : t("admin:users.deactivated"));
    } catch (e) {
      toast.error(translateError(e));
    }
  };

  const columns = useMemo<ColumnDef<UserOut>[]>(
    () => [
      {
        id: "name",
        accessorFn: (u) => displayName(u, i18n.language),
        header: t("admin:users.name"),
        meta: { label: t("admin:users.name") },
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="truncate font-medium text-fg">{displayName(row.original, i18n.language)}</div>
            <Code>{row.original.username}</Code>
          </div>
        ),
      },
      {
        id: "roles",
        accessorFn: (u) => u.roles.join(","),
        header: t("admin:users.roles"),
        meta: { label: t("admin:users.roles") },
        enableSorting: false,
        cell: ({ row }) => <RoleBadges roles={row.original.roles} />,
      },
      {
        id: "status",
        accessorFn: (u) => (u.is_active ? 1 : 0),
        header: t("admin:users.status"),
        meta: { label: t("admin:users.status") },
        cell: ({ row }) => <UserStatus user={row.original} />,
      },
      {
        id: "last_login",
        accessorFn: (u) => u.last_login ?? "",
        header: t("admin:users.lastLogin"),
        meta: { label: t("admin:users.lastLogin") },
        cell: ({ row }) =>
          row.original.last_login ? (
            <DateText value={row.original.last_login} format="datetime" className="text-muted" />
          ) : (
            <span className="text-muted">{t("admin:users.never")}</span>
          ),
      },
    ],
    [t, i18n.language],
  );

  return (
    <AdminPage
      section="users"
      title={t("admin:sections.users.title")}
      description={t("admin:sections.users.description")}
      actions={
        <Button
          onClick={() => {
            setDialog({ kind: "create" });
          }}
        >
          <Plus />
          {t("admin:users.create")}
        </Button>
      }
    >
      <FilterBar>
        <SearchInput
          label={t("admin:users.search")}
          placeholder={t("admin:users.search")}
          onSearch={(q) => {
            setFilters((f) => ({ ...f, q: q || undefined }));
          }}
          className="sm:max-w-xs"
        />
        <FilterSelect
          label={t("admin:users.roleFilter")}
          allLabel={t("admin:users.allRoles")}
          value={filters.role}
          onChange={(role) => {
            setFilters((f) => ({ ...f, role: role as RoleCode | undefined }));
          }}
          options={ROLES.map((r) => ({ value: r, label: t(`common:roles.${r}`) }))}
        />
        <FilterSelect
          label={t("admin:users.statusFilter")}
          allLabel={t("admin:common.all")}
          value={filters.active === undefined ? undefined : String(filters.active)}
          onChange={(v) => {
            setFilters((f) => ({ ...f, active: v === undefined ? undefined : v === "true" }));
          }}
          options={[
            { value: "true", label: t("admin:common.active") },
            { value: "false", label: t("admin:common.inactive") },
          ]}
        />
      </FilterBar>
      <QueryState loading={users.isPending} error={users.error} onRetry={() => void users.refetch()}>
        <DataTable
          caption={t("admin:users.caption")}
          columns={columns}
          data={users.data?.items ?? []}
          getRowId={(u) => String(u.id)}
          loading={users.isFetching && !users.data}
          onRowClick={(user) => {
            setDialog({ kind: "edit", user });
          }}
          rowLabel={(u) => t("admin:users.open", { name: displayName(u, i18n.language) })}
          rowActions={(user) => [
            {
              label: t("admin:users.edit"),
              icon: <Pencil />,
              onSelect: () => {
                setDialog({ kind: "edit", user });
              },
            },
            {
              label: t("admin:users.resetPassword"),
              icon: <KeyRound />,
              disabled: user.is_superuser,
              onSelect: () => {
                setDialog({ kind: "reset", user });
              },
            },
            {
              label: t("admin:users.unlock"),
              icon: <LockOpen />,
              disabled: !user.locked && user.failed_login_count === 0,
              onSelect: () => {
                setDialog({ kind: "unlock", user });
              },
            },
            user.is_active
              ? {
                  label: t("admin:users.deactivate"),
                  icon: <UserX />,
                  destructive: true,
                  separated: true,
                  disabled: user.id === me?.id || user.is_superuser,
                  onSelect: () => void setActive(user, false),
                }
              : {
                  label: t("admin:users.activate"),
                  icon: <UserCheck />,
                  separated: true,
                  onSelect: () => void setActive(user, true),
                },
          ]}
        />
      </QueryState>

      {dialog?.kind === "create" ? (
        <CreateUserDialog
          onClose={() => {
            setDialog(null);
          }}
        />
      ) : null}
      {dialog?.kind === "edit" ? (
        <EditUserDialog
          user={dialog.user}
          onClose={() => {
            setDialog(null);
          }}
        />
      ) : null}
      {dialog?.kind === "reset" ? (
        <ResetPasswordDialog
          user={dialog.user}
          onClose={() => {
            setDialog(null);
          }}
        />
      ) : null}
      {dialog?.kind === "unlock" ? (
        <UnlockDialog
          user={dialog.user}
          onClose={() => {
            setDialog(null);
          }}
        />
      ) : null}
    </AdminPage>
  );
}

function RoleBadges({ roles: codes }: { roles: readonly string[] }) {
  const { t } = useTranslation("common");
  return (
    <div className="flex flex-wrap gap-1">
      {codes.map((role) => (
        <Badge key={role} variant="soft">
          {(ROLES as readonly string[]).includes(role) ? t(`roles.${role as RoleCode}`) : role}
        </Badge>
      ))}
    </div>
  );
}

function UserStatus({ user }: { user: UserOut }) {
  const { t } = useTranslation("admin");
  return (
    <div className="flex flex-wrap gap-1">
      <ActiveBadge active={user.is_active} />
      {user.locked ? <Badge variant="danger">{t("users.locked")}</Badge> : null}
      {user.must_change_password ? <Badge variant="warning">{t("users.mustChange")}</Badge> : null}
    </div>
  );
}

function CreateUserDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation("admin");
  const create = useCreateUser();
  const form = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { username: "", full_name_ar: "", full_name_en: "", phone: "", roles: [], password: "" },
  });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("users.create")}
      description={t("users.createHint")}
      form={form}
      error={create.error}
      wide
      onSubmit={async (values) => {
        await create.mutateAsync(values);
        toast.success(t("users.created", { username: values.username }));
        onClose();
      }}
    >
      <TextField
        control={form.control}
        name="username"
        label={t("users.username")}
        dir="ltr"
        autoComplete="off"
        required
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField control={form.control} name="full_name_ar" label={t("users.fullNameAr")} dir="rtl" />
        <TextField control={form.control} name="full_name_en" label={t("users.fullNameEn")} dir="ltr" />
      </div>
      <TextField control={form.control} name="phone" label={t("users.phone")} type="tel" dir="ltr" />
      <RolesField control={form.control} name="roles" />
      <PasswordField
        control={form.control}
        name="password"
        label={t("users.tempPassword")}
        description={t("users.tempPasswordHint")}
        autoComplete="new-password"
        required
      />
    </FormDialog>
  );
}

function EditUserDialog({ user, onClose }: { user: UserOut; onClose: () => void }) {
  const { t } = useTranslation("admin");
  const update = useUpdateUser();
  const form = useForm<EditValues>({
    resolver: zodResolver(editSchema),
    defaultValues: {
      full_name_ar: user.full_name_ar,
      full_name_en: user.full_name_en,
      phone: user.phone,
      roles: user.roles.filter((r): r is RoleCode => (ROLES as readonly string[]).includes(r)),
      is_active: user.is_active,
    },
  });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("users.editTitle", { username: user.username })}
      form={form}
      error={update.error}
      wide
      onSubmit={async (values) => {
        await update.mutateAsync({ id: user.id, body: values });
        toast.success(t("users.saved"));
        onClose();
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField control={form.control} name="full_name_ar" label={t("users.fullNameAr")} dir="rtl" />
        <TextField control={form.control} name="full_name_en" label={t("users.fullNameEn")} dir="ltr" />
      </div>
      <TextField control={form.control} name="phone" label={t("users.phone")} type="tel" dir="ltr" />
      <RolesField control={form.control} name="roles" />
      <SwitchField control={form.control} name="is_active" label={t("common.active")} />
    </FormDialog>
  );
}

function ResetPasswordDialog({ user, onClose }: { user: UserOut; onClose: () => void }) {
  const { t } = useTranslation("admin");
  const reset = useResetPassword();
  const form = useForm<ResetValues>({ resolver: zodResolver(resetSchema), defaultValues: { password: "" } });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("users.resetTitle", { username: user.username })}
      description={t("users.resetHint")}
      form={form}
      error={reset.error}
      onSubmit={async (values) => {
        await reset.mutateAsync({ id: user.id, newPassword: values.password });
        toast.success(t("users.resetDone"));
        onClose();
      }}
    >
      <PasswordField
        control={form.control}
        name="password"
        label={t("users.tempPassword")}
        autoComplete="new-password"
        required
      />
    </FormDialog>
  );
}

function UnlockDialog({ user, onClose }: { user: UserOut; onClose: () => void }) {
  const { t } = useTranslation("admin");
  const unlock = useUnlockUser();
  const form = useForm<UnlockValues>({ resolver: zodResolver(unlockSchema), defaultValues: { reason: "" } });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("users.unlockTitle", { username: user.username })}
      description={t("users.unlockHint")}
      form={form}
      error={unlock.error}
      submitLabel={t("users.unlock")}
      onSubmit={async (values) => {
        await unlock.mutateAsync({ id: user.id, reason: values.reason });
        toast.success(t("users.unlocked"));
        onClose();
      }}
    >
      <TextareaField control={form.control} name="reason" label={t("common.reason")} rows={3} required />
    </FormDialog>
  );
}
