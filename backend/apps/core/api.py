"""Core routers.

* ``/api/auth``: CSRF cookie, login, logout, current user, preferences, password change.
* ``/api/core``: administration (FEATURES 0.2, 0.3, 13.1-13.7): users and roles, the
  permission matrix, center profile and logo, policies, departments, rooms, doctors and their
  weekly schedules, reason codes, numbering sequences and print templates.

Routers stay thin: each operation checks one permission and calls one service function.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from ninja import File, Query, Router, Status
from ninja.errors import AuthenticationError
from ninja.files import UploadedFile

from api.pagination import paginate
from api.permissions import require_perm
from api.ping import add_ping
from api.schemas import ERROR_RESPONSES, ErrorOut, Page
from api.security import session_auth_pending_ok
from apps.core import services
from apps.core.models import CenterProfile, DoctorProfile, Policy, ReasonCode, Room, User
from apps.core.schemas import (
    CenterProfileIn,
    CenterProfileOut,
    ChangePasswordIn,
    DepartmentIn,
    DepartmentListParams,
    DepartmentOut,
    DepartmentPatch,
    DoctorCandidateOut,
    DoctorIn,
    DoctorListParams,
    DoctorOut,
    DoctorPatch,
    LoginIn,
    MeOut,
    PaperCode,
    PermissionMatrixIn,
    PermissionMatrixOut,
    PolicyIn,
    PolicyOut,
    PreferencesPatch,
    PrintDocumentCode,
    PrintTemplateIn,
    PrintTemplateOut,
    ReasonCodeIn,
    ReasonCodeListParams,
    ReasonCodeOut,
    ReasonCodePatch,
    ReasonIn,
    ResetPasswordIn,
    RoleOut,
    RoomIn,
    RoomListParams,
    RoomOut,
    RoomPatch,
    ScheduleIn,
    SequenceParams,
    SequencesOut,
    UserIn,
    UserListParams,
    UserOut,
    UserPatch,
)

auth_router = Router(tags=["auth"])
core_router = Router(tags=["core"])
add_ping(core_router, "core")


def _current_user(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - the router's auth guarantees a User
        raise AuthenticationError()
    return user


@auth_router.get(
    "/csrf",
    auth=None,
    response={204: None},
    operation_id="auth_get_csrf",
    summary="Set the csrftoken cookie",
)
def get_csrf(request: HttpRequest) -> Status[None]:
    get_token(request)
    return Status(204, None)


@auth_router.post(
    "/login",
    auth=None,
    response={
        200: MeOut,
        401: ErrorOut,
        403: ErrorOut,
        422: ErrorOut,
        423: ErrorOut,
        429: ErrorOut,
    },
    operation_id="auth_login",
    summary="Log in with username and password",
    description=(
        "401 INVALID_CREDENTIALS on a wrong username/password. The 5th consecutive failure "
        "for a username (existing or not) locks it for 15 minutes; while locked every "
        "attempt returns 423 ACCOUNT_LOCKED with details.locked_until and "
        "details.retry_after_seconds. Too many failures from one client address return "
        "429 RATE_LIMITED with details.retry_after_seconds. A successful login rotates the "
        "session and the csrftoken cookie."
    ),
)
def login(request: HttpRequest, payload: LoginIn) -> dict[str, Any]:
    return services.login(request, payload.username, payload.password)


@auth_router.post(
    "/logout",
    auth=None,
    response={204: None, 403: ErrorOut},
    operation_id="auth_logout",
    summary="Log out (idempotent)",
)
def logout(request: HttpRequest) -> Status[None]:
    services.logout(request)
    return Status(204, None)


@auth_router.get(
    "/me",
    auth=session_auth_pending_ok,
    response={200: MeOut, 401: ErrorOut},
    operation_id="auth_get_me",
    summary="Current user, roles, effective permissions and preferences",
)
def me(request: HttpRequest) -> dict[str, Any]:
    return services.me_payload(_current_user(request))


@auth_router.patch(
    "/me/preferences",
    auth=session_auth_pending_ok,
    response={200: MeOut, 401: ErrorOut, 403: ErrorOut, 422: ErrorOut},
    operation_id="auth_update_preferences",
    summary="Update language and/or theme",
)
def update_preferences(request: HttpRequest, payload: PreferencesPatch) -> dict[str, Any]:
    return services.update_preferences(
        _current_user(request), language=payload.language, theme=payload.theme
    )


@auth_router.post(
    "/change-password",
    auth=session_auth_pending_ok,
    response={204: None, 401: ErrorOut, 403: ErrorOut, 409: ErrorOut, 422: ErrorOut, 423: ErrorOut},
    operation_id="auth_change_password",
    summary="Change own password",
    description=(
        "409 PASSWORD_INVALID with details.reason = old_password_incorrect | "
        "password_unchanged | password_rejected (then details.messages lists why). "
        "Wrong current passwords count toward the login lockout: the one that locks the "
        "account ends the session and returns 423 ACCOUNT_LOCKED, as does any attempt "
        "while the account is locked."
    ),
)
def change_password(request: HttpRequest, payload: ChangePasswordIn) -> Status[None]:
    services.change_password(
        request, _current_user(request), payload.old_password, payload.new_password
    )
    return Status(204, None)


# =========================================================================================
# /api/core: administration
# =========================================================================================

_READ: dict[int, type[ErrorOut]] = {401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut}
_WRITE: dict[int, type[ErrorOut]] = {**ERROR_RESPONSES, 404: ErrorOut}


# --- Users ------------------------------------------------------------------------------


@core_router.get(
    "/users",
    response={200: Page[UserOut], **_READ},
    operation_id="core_list_users",
    summary="Staff accounts, filtered by text, role and active flag (paged)",
)
@require_perm("core.manage_users")
def list_users(request: HttpRequest, params: Query[UserListParams]) -> dict[str, Any]:
    rows = services.list_users(q=params.q, role=params.role, active=params.active)
    return paginate(rows, params.page, params.page_size)


@core_router.post(
    "/users",
    response={201: UserOut, **_WRITE},
    operation_id="core_create_user",
    summary="Create a staff account with roles and a temporary password",
    description=(
        "The account must change its password at first login. 409 INVALID_USERNAME, "
        "USERNAME_TAKEN, ROLE_REQUIRED, ROLE_UNKNOWN, PASSWORD_INVALID (details.messages)."
    ),
)
@require_perm("core.manage_users")
def create_user(request: HttpRequest, payload: UserIn) -> Status[User]:
    user = services.create_user(
        _current_user(request),
        username=payload.username,
        password=payload.password,
        role_codes=payload.roles,
        full_name_ar=payload.full_name_ar,
        full_name_en=payload.full_name_en,
        phone=payload.phone,
    )
    return Status(201, user)


@core_router.get(
    "/users/{user_id}",
    response={200: UserOut, **_READ},
    operation_id="core_get_user",
    summary="One staff account",
)
@require_perm("core.manage_users")
def get_user(request: HttpRequest, user_id: int) -> User:
    return services.get_user(user_id)


@core_router.patch(
    "/users/{user_id}",
    response={200: UserOut, **_WRITE},
    operation_id="core_update_user",
    summary="Edit names, phone, active flag and roles",
    description=(
        "409 SUPERUSER_PROTECTED, CANNOT_DEACTIVATE_SELF, ROLE_REQUIRED, LAST_ADMIN (the last "
        "active administrator cannot be deactivated or lose the admin role)."
    ),
)
@require_perm("core.manage_users")
def update_user(request: HttpRequest, user_id: int, payload: UserPatch) -> User:
    changes = payload.changes()
    roles = changes.pop("roles", None)
    return services.update_user(_current_user(request), user_id, role_codes=roles, **changes)


@core_router.post(
    "/users/{user_id}/reset-password",
    response={200: UserOut, **_WRITE},
    operation_id="core_reset_password",
    summary="Set a temporary password; the user must change it at next login",
    description="Ends the user's sessions. 409 SUPERUSER_PROTECTED, PASSWORD_INVALID.",
)
@require_perm("core.manage_users")
def reset_password(request: HttpRequest, user_id: int, payload: ResetPasswordIn) -> User:
    return services.reset_password(request, _current_user(request), user_id, payload.new_password)


@core_router.post(
    "/users/{user_id}/unlock",
    response={200: UserOut, **_WRITE},
    operation_id="core_unlock_user",
    summary="Clear a login lockout, with a reason (audited)",
    description="409 REASON_REQUIRED, SUPERUSER_PROTECTED, USER_NOT_LOCKED.",
)
@require_perm("core.manage_users")
def unlock_user(request: HttpRequest, user_id: int, payload: ReasonIn) -> User:
    return services.unlock_user(request, _current_user(request), user_id, payload.reason)


# --- Roles and the permission matrix ------------------------------------------------------


@core_router.get(
    "/roles",
    response={200: list[RoleOut], **_READ},
    operation_id="core_list_roles",
    summary="Roles with how many active users hold each",
)
@require_perm("core.manage_users")
def list_roles(request: HttpRequest) -> list[dict[str, Any]]:
    return services.role_summaries()


@core_router.get(
    "/permissions/matrix",
    response={200: PermissionMatrixOut, **_READ},
    operation_id="core_get_permission_matrix",
    summary="Every permission code and the roles that grant it",
)
@require_perm("core.manage_roles")
def get_permission_matrix(request: HttpRequest) -> dict[str, Any]:
    return services.permission_matrix()


@core_router.put(
    "/permissions/matrix",
    response={200: PermissionMatrixOut, **_WRITE},
    operation_id="core_update_permission_matrix",
    summary="Grant or revoke permissions per role, with a reason (audited)",
    description=(
        "Only the cells sent change. 409 REASON_REQUIRED, PERMISSION_UNKNOWN, ROLE_UNKNOWN, "
        "MATRIX_CHANGE_CONFLICT, PERMISSION_PROTECTED (admin keeps core.manage_users and "
        "core.manage_roles)."
    ),
)
@require_perm("core.manage_roles")
def update_permission_matrix(request: HttpRequest, payload: PermissionMatrixIn) -> dict[str, Any]:
    return services.update_permission_matrix(
        _current_user(request),
        [(c.role, c.code, c.allowed) for c in payload.changes],
        reason=payload.reason,
    )


# --- Center profile and logo --------------------------------------------------------------


@core_router.get(
    "/center",
    response={200: CenterProfileOut, **_READ},
    operation_id="core_get_center_profile",
    summary="The center's name, address and registration numbers",
)
@require_perm("core.manage_settings")
def get_center_profile(request: HttpRequest) -> CenterProfile:
    return services.center_profile()


@core_router.put(
    "/center",
    response={200: CenterProfileOut, **_WRITE},
    operation_id="core_update_center_profile",
    summary="Save the center profile printed on documents",
)
@require_perm("core.manage_settings")
def update_center_profile(request: HttpRequest, payload: CenterProfileIn) -> CenterProfile:
    return services.update_center_profile(_current_user(request), **payload.dict())


@core_router.post(
    "/center/logo",
    response={200: CenterProfileOut, **_WRITE},
    operation_id="core_upload_center_logo",
    summary="Upload the center logo (PNG, JPEG, GIF or WebP, at most 1 MB)",
    description="Stored under MEDIA_ROOT. 409 LOGO_TOO_LARGE, LOGO_INVALID_TYPE.",
)
@require_perm("core.manage_settings")
def upload_center_logo(request: HttpRequest, file: File[UploadedFile]) -> CenterProfile:
    return services.set_center_logo(_current_user(request), file)


@core_router.delete(
    "/center/logo",
    response={200: CenterProfileOut, **_WRITE},
    operation_id="core_delete_center_logo",
    summary="Remove the center logo",
)
@require_perm("core.manage_settings")
def delete_center_logo(request: HttpRequest) -> CenterProfile:
    return services.clear_center_logo(_current_user(request))


@core_router.get(
    "/center/logo",
    response={200: None, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    operation_id="core_get_center_logo",
    summary="The center logo image (any signed-in user: it is printed on documents)",
    openapi_extra={
        "responses": {
            200: {
                "description": "The logo image",
                "content": {"image/*": {"schema": {"type": "string", "format": "binary"}}},
            }
        }
    },
)
def get_center_logo(request: HttpRequest) -> HttpResponse:
    data, content_type = services.center_logo()
    response = HttpResponse(data, content_type=content_type)
    response["Cache-Control"] = "private, max-age=86400"
    response["X-Content-Type-Options"] = "nosniff"
    return response


# --- Policy -------------------------------------------------------------------------------


@core_router.get(
    "/policy",
    response={200: PolicyOut, **_READ},
    operation_id="core_get_policy",
    summary="Center-wide policy switches",
)
@require_perm("core.manage_settings")
def get_policy(request: HttpRequest) -> Policy:
    return services.policy()


@core_router.put(
    "/policy",
    response={200: PolicyOut, **_WRITE},
    operation_id="core_update_policy",
    summary="Save the policy switches (pay-first stays on: invariant 1)",
    description="422 VALIDATION_ERROR with details.fields for out-of-range values.",
)
@require_perm("core.manage_settings")
def update_policy(request: HttpRequest, payload: PolicyIn) -> Policy:
    return services.update_policy(_current_user(request), **payload.dict())


# --- Departments, rooms, doctors ----------------------------------------------------------


@core_router.get(
    "/departments",
    response={200: list[DepartmentOut], **_READ},
    operation_id="core_list_departments",
    summary="Departments with their room and active doctor counts (catalog reference data)",
)
@require_perm("catalog.view")
def list_departments(request: HttpRequest, params: Query[DepartmentListParams]) -> list[Any]:
    return list(services.list_departments(active=params.active))


@core_router.post(
    "/departments",
    response={201: DepartmentOut, **_WRITE},
    operation_id="core_create_department",
    summary="Add a department",
    description="409 INVALID_CODE, DEPARTMENT_CODE_TAKEN.",
)
@require_perm("core.manage_departments")
def create_department(request: HttpRequest, payload: DepartmentIn) -> Status[Any]:
    return Status(201, services.create_department(_current_user(request), **payload.dict()))


@core_router.patch(
    "/departments/{department_id}",
    response={200: DepartmentOut, **_WRITE},
    operation_id="core_update_department",
    summary="Rename, reorder or (de)activate a department",
)
@require_perm("core.manage_departments")
def update_department(request: HttpRequest, department_id: int, payload: DepartmentPatch) -> Any:
    return services.update_department(_current_user(request), department_id, **payload.changes())


@core_router.get(
    "/rooms",
    response={200: list[RoomOut], **_READ},
    operation_id="core_list_rooms",
    summary="Rooms, optionally of one department",
)
@require_perm("core.manage_departments")
def list_rooms(request: HttpRequest, params: Query[RoomListParams]) -> list[Room]:
    return list(services.list_rooms(department_id=params.department_id, active=params.active))


@core_router.post(
    "/rooms",
    response={201: RoomOut, **_WRITE},
    operation_id="core_create_room",
    summary="Add a room",
    description="409 INVALID_CODE, ROOM_CODE_TAKEN, DEPARTMENT_INACTIVE.",
)
@require_perm("core.manage_departments")
def create_room(request: HttpRequest, payload: RoomIn) -> Status[Room]:
    return Status(201, services.create_room(_current_user(request), **payload.dict()))


@core_router.patch(
    "/rooms/{room_id}",
    response={200: RoomOut, **_WRITE},
    operation_id="core_update_room",
    summary="Rename, move or (de)activate a room",
)
@require_perm("core.manage_departments")
def update_room(request: HttpRequest, room_id: int, payload: RoomPatch) -> Room:
    return services.update_room(_current_user(request), room_id, **payload.changes())


@core_router.get(
    "/doctors",
    response={200: list[DoctorOut], **_READ},
    operation_id="core_list_doctors",
    summary="Doctors with department, specialty, consultation fee service and weekly hours",
)
@require_perm("core.manage_departments")
def list_doctors(request: HttpRequest, params: Query[DoctorListParams]) -> list[DoctorProfile]:
    return list(services.list_doctors(department_id=params.department_id, active=params.active))


@core_router.get(
    "/doctors/candidates",
    response={200: list[DoctorCandidateOut], **_READ},
    operation_id="core_list_doctor_candidates",
    summary="Active users with the doctor role and no doctor profile yet (names only)",
)
@require_perm("core.manage_departments")
def list_doctor_candidates(request: HttpRequest) -> list[User]:
    return list(services.list_doctor_candidates())


@core_router.post(
    "/doctors",
    response={201: DoctorOut, **_WRITE},
    operation_id="core_create_doctor",
    summary="Give a user with the doctor role a clinical profile",
    description=(
        "409 DOCTOR_ROLE_REQUIRED, DOCTOR_PROFILE_EXISTS, DEPARTMENT_INACTIVE, "
        "CONSULTATION_SERVICE_INVALID."
    ),
)
@require_perm("core.manage_departments")
def create_doctor(request: HttpRequest, payload: DoctorIn) -> Status[DoctorProfile]:
    return Status(201, services.create_doctor(_current_user(request), **payload.dict()))


@core_router.patch(
    "/doctors/{doctor_id}",
    response={200: DoctorOut, **_WRITE},
    operation_id="core_update_doctor",
    summary="Edit a doctor's department, specialty, fee service or active flag",
)
@require_perm("core.manage_departments")
def update_doctor(request: HttpRequest, doctor_id: int, payload: DoctorPatch) -> DoctorProfile:
    return services.update_doctor(_current_user(request), doctor_id, **payload.changes())


@core_router.put(
    "/doctors/{doctor_id}/schedule",
    response={200: DoctorOut, **_WRITE},
    operation_id="core_set_doctor_schedule",
    summary="Replace a doctor's weekly clinic hours",
    description=(
        "Sessions of one weekday never overlap. 409 SCHEDULE_INVALID_SPAN, "
        "SCHEDULE_INVALID_SLOT, SCHEDULE_OVERLAP, SCHEDULE_TOO_LONG, ROOM_INACTIVE."
    ),
)
@require_perm("core.manage_departments")
def set_doctor_schedule(request: HttpRequest, doctor_id: int, payload: ScheduleIn) -> DoctorProfile:
    return services.set_doctor_schedule(
        _current_user(request), doctor_id, [s.dict() for s in payload.sessions]
    )


# --- Reason codes -------------------------------------------------------------------------


@core_router.get(
    "/reason-codes",
    response={200: list[ReasonCodeOut], **_READ},
    operation_id="core_list_reason_codes",
    summary="Reason codes by category (any signed-in user: every reason dialog reads them)",
)
def list_reason_codes(request: HttpRequest, params: Query[ReasonCodeListParams]) -> list[Any]:
    return list(services.list_reason_codes(category=params.category, active=params.active))


@core_router.post(
    "/reason-codes",
    response={201: ReasonCodeOut, **_WRITE},
    operation_id="core_create_reason_code",
    summary="Add a reason code to a category",
    description="409 INVALID_CODE, REASON_CATEGORY_UNKNOWN, REASON_CODE_TAKEN.",
)
@require_perm("core.manage_reason_codes")
def create_reason_code(request: HttpRequest, payload: ReasonCodeIn) -> Status[ReasonCode]:
    return Status(201, services.create_reason_code(_current_user(request), **payload.dict()))


@core_router.patch(
    "/reason-codes/{reason_id}",
    response={200: ReasonCodeOut, **_WRITE},
    operation_id="core_update_reason_code",
    summary="Edit labels, note flag, order or active flag of a reason code",
    description="409 REASON_CATEGORY_EMPTY: each category keeps one active reason.",
)
@require_perm("core.manage_reason_codes")
def update_reason_code(request: HttpRequest, reason_id: int, payload: ReasonCodePatch) -> Any:
    return services.update_reason_code(_current_user(request), reason_id, **payload.changes())


# --- Numbering and print templates --------------------------------------------------------


@core_router.get(
    "/sequences",
    response={200: SequencesOut, **_READ},
    operation_id="core_list_sequences",
    summary="Document numbering counters of a year (last and next number per type)",
)
@require_perm("core.manage_settings")
def list_sequences(request: HttpRequest, params: Query[SequenceParams]) -> dict[str, Any]:
    return services.sequences(params.year)


@core_router.get(
    "/print-templates",
    response={200: list[PrintTemplateOut], **_READ},
    operation_id="core_list_print_templates",
    summary="Header, footer and logo switch of every printed document per paper size",
)
@require_perm("core.manage_print_templates")
def list_print_templates(request: HttpRequest) -> list[dict[str, Any]]:
    return services.print_templates()


@core_router.put(
    "/print-templates/{document}/{paper}",
    response={200: PrintTemplateOut, **_WRITE},
    operation_id="core_save_print_template",
    summary="Save the header, footer and logo switch of one document on one paper size",
)
@require_perm("core.manage_print_templates")
def save_print_template(
    request: HttpRequest, document: PrintDocumentCode, paper: PaperCode, payload: PrintTemplateIn
) -> dict[str, Any]:
    return services.save_print_template(_current_user(request), document, paper, **payload.dict())
