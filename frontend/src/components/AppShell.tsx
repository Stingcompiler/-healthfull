import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { KeyRound, LogOut, Menu, Palette, Search } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { NAV_GROUP_ORDER, type NavItem } from "@/app/nav-types";
import { Brand, BrandMark } from "@/components/BrandMark";
import { KbdCombo } from "@/components/Kbd";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useCurrentUser, useLogout } from "@/lib/auth/hooks";
import { isKnownRole } from "@/lib/auth/permissions";
import { useShortcut } from "@/lib/hooks/use-shortcut";
import { useDirection, useLanguage } from "@/lib/i18n-hooks";
import { initials, pickName } from "@/lib/names";
import { cn } from "@/lib/utils";

const SEARCH_SHORTCUT = "mod+k";

export interface AppShellProps {
  /** Navigation entries the current user may see (already permission-filtered). */
  nav: readonly NavItem[];
  /** Replaces the default quick-search trigger in the top bar. */
  search?: ReactNode;
  children: ReactNode;
}

/**
 * Authenticated layout.
 *   >= lg  full sidebar with group headings
 *   md     icon rail with tooltips
 *   < md   top bar with drawer menu + bottom navigation
 */
export function AppShell({ nav, search, children }: AppShellProps) {
  const { t } = useTranslation(["common", "nav"]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const listed = useMemo(() => nav.filter((item) => !item.hidden), [nav]);
  const bottomItems = listed.slice(0, 4);

  // ⌘K on macOS; Ctrl+K everywhere (most clinic PCs run Windows).
  useShortcut([SEARCH_SHORTCUT, "ctrl+k"], () => {
    setCommandOpen((open) => !open);
  });

  return (
    <div className="min-h-dvh bg-bg">
      <a
        href="#main"
        className="sr-only z-[60] rounded-control bg-primary px-4 py-2 text-primary-fg focus:not-sr-only focus:fixed focus:start-4 focus:top-4"
      >
        {t("a11y.skipToContent")}
      </a>

      {/* Sidebar (lg) / rail (md) */}
      <aside
        data-slot="app-sidebar"
        className="fixed inset-y-0 start-0 z-30 hidden w-[72px] flex-col border-e border-border bg-surface md:flex lg:w-64"
      >
        <div className="flex h-16 shrink-0 items-center justify-center border-b border-border px-3 lg:justify-start lg:px-5">
          <Link
            to="/"
            className="rounded-control focus-visible:ring-3 focus-visible:ring-ring/35 focus-visible:outline-none"
          >
            <BrandMark className="lg:hidden" />
            <Brand className="hidden lg:flex" />
          </Link>
        </div>
        <nav aria-label={t("a11y.mainNavigation")} className="flex-1 scrollbar-thin overflow-y-auto px-2 py-4 lg:px-3">
          <NavGroups items={listed} variant="sidebar" />
        </nav>
      </aside>

      <div className="flex min-h-dvh min-w-0 flex-col md:ps-[72px] lg:ps-64">
        {/* Top bar */}
        <header
          data-slot="app-topbar"
          className="sticky top-0 z-20 flex h-16 shrink-0 items-center gap-2 border-b border-border bg-surface/90 px-3 backdrop-blur supports-[backdrop-filter]:bg-surface/75 md:px-6"
        >
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            aria-label={t("actions.openMenu")}
            aria-expanded={drawerOpen}
            onClick={() => {
              setDrawerOpen(true);
            }}
          >
            <Menu />
          </Button>
          <Link to="/" className="min-w-0 md:hidden" aria-label={t("appName")}>
            <BrandMark className="size-8" />
          </Link>
          <div className="flex min-w-0 flex-1 items-center">
            {search ?? (
              <QuickSearchTrigger
                onOpen={() => {
                  setCommandOpen(true);
                }}
              />
            )}
          </div>
          <div className="flex shrink-0 items-center gap-0.5">
            <LanguageSwitcher variant="icon" className="lg:hidden" />
            <LanguageSwitcher variant="button" className="hidden lg:inline-flex" />
            <ThemeSwitcher />
            <UserMenu />
          </div>
        </header>

        <main id="main" tabIndex={-1} className="min-w-0 flex-1 px-4 pt-5 pb-28 outline-none md:px-6 md:py-6 lg:px-8">
          <div className="mx-auto w-full max-w-7xl min-w-0">{children}</div>
        </main>
      </div>

      {/* Phone bottom navigation */}
      <nav
        aria-label={t("a11y.mobileNavigation")}
        data-slot="app-bottom-nav"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface/95 safe-bottom backdrop-blur md:hidden"
      >
        <ul className="mx-auto grid h-16 max-w-md grid-cols-5">
          {bottomItems.map((item) => (
            <li key={item.id} className="min-w-0">
              <NavLink item={item} variant="bottom" />
            </li>
          ))}
          <li className="min-w-0">
            <button
              type="button"
              onClick={() => {
                setDrawerOpen(true);
              }}
              className="flex h-full w-full flex-col items-center justify-center gap-1 text-[11px] font-medium text-muted hover:text-fg focus-visible:ring-3 focus-visible:ring-ring/35 focus-visible:outline-none"
            >
              <Menu className="size-5" aria-hidden="true" />
              <span className="max-w-full truncate px-1">{t("nav:shell.more")}</span>
            </button>
          </li>
        </ul>
      </nav>

      {/* Phone drawer */}
      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent side="start" className="gap-0 p-0">
          <SheetHeader className="border-b border-border">
            <SheetTitle asChild>
              <div>
                <Brand />
              </div>
            </SheetTitle>
            <SheetDescription className="sr-only">{t("a11y.mainNavigation")}</SheetDescription>
          </SheetHeader>
          <nav aria-label={t("a11y.mainNavigation")} className="flex-1 overflow-y-auto px-3 py-4">
            <NavGroups
              items={listed}
              variant="drawer"
              onNavigate={() => {
                setDrawerOpen(false);
              }}
            />
          </nav>
        </SheetContent>
      </Sheet>

      <CommandMenu open={commandOpen} onOpenChange={setCommandOpen} items={nav} />
    </div>
  );
}

function QuickSearchTrigger({ onOpen }: { onOpen: () => void }) {
  const { t } = useTranslation();
  return (
    <>
      <Button variant="ghost" size="icon" className="sm:hidden" aria-label={t("search.open")} onClick={onOpen}>
        <Search />
      </Button>
      <button
        type="button"
        onClick={onOpen}
        aria-label={t("search.open")}
        className={cn(
          "hidden h-10 w-full max-w-md items-center gap-2 rounded-control border border-border bg-subtle px-3 text-sm text-muted sm:flex",
          "transition-colors hover:border-border-strong/60 hover:bg-surface focus-visible:ring-3 focus-visible:ring-ring/35 focus-visible:outline-none",
        )}
      >
        <Search className="size-4 shrink-0" aria-hidden="true" />
        <span className="flex-1 truncate text-start">{t("search.globalPlaceholder")}</span>
        <KbdCombo combo={SEARCH_SHORTCUT} />
      </button>
    </>
  );
}

type NavVariant = "sidebar" | "drawer" | "bottom";

function NavGroups({
  items,
  variant,
  onNavigate,
}: {
  items: readonly NavItem[];
  variant: Exclude<NavVariant, "bottom">;
  onNavigate?: () => void;
}) {
  const { t } = useTranslation("nav");
  return (
    <div className="flex flex-col gap-5">
      {NAV_GROUP_ORDER.map((group) => {
        const groupItems = items.filter((item) => item.group === group);
        if (groupItems.length === 0) return null;
        return (
          <div key={group} className="flex flex-col gap-1">
            <div
              className={cn(
                "px-3 pb-1 text-[11px] font-semibold tracking-wide text-muted uppercase",
                variant === "sidebar" && "hidden lg:block",
              )}
            >
              {t(`groups.${group}`)}
            </div>
            {variant === "sidebar" ? <div className="mx-auto h-px w-6 bg-border lg:hidden" aria-hidden="true" /> : null}
            <ul className="flex flex-col gap-0.5">
              {groupItems.map((item) => (
                <li key={item.id}>
                  <NavLink item={item} variant={variant} onNavigate={onNavigate} />
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

function NavLink({ item, variant, onNavigate }: { item: NavItem; variant: NavVariant; onNavigate?: () => void }) {
  const { t } = useTranslation("nav");
  const dir = useDirection();
  const Icon = item.icon;
  const label = t(`items.${item.labelKey}`);

  if (variant === "bottom") {
    return (
      <Link
        to={item.to}
        activeOptions={{ exact: item.exact ?? false }}
        data-testid={`nav-${item.id}`}
        className={cn(
          "flex h-full flex-col items-center justify-center gap-1 text-[11px] font-medium text-muted transition-colors",
          "hover:text-fg focus-visible:ring-3 focus-visible:ring-ring/35 focus-visible:outline-none",
          "data-[status=active]:text-primary-strong",
        )}
      >
        <Icon className="size-5" aria-hidden="true" />
        <span className="max-w-full truncate px-1">{label}</span>
      </Link>
    );
  }

  const link = (
    <Link
      to={item.to}
      activeOptions={{ exact: item.exact ?? false }}
      data-testid={`nav-${item.id}`}
      onClick={onNavigate}
      className={cn(
        "group flex h-10 items-center gap-3 rounded-control px-3 text-sm font-medium text-muted transition-colors",
        "hover:bg-accent hover:text-fg focus-visible:ring-3 focus-visible:ring-ring/35 focus-visible:outline-none",
        "data-[status=active]:bg-primary-soft data-[status=active]:text-primary-strong",
        variant === "sidebar" && "justify-center px-0 lg:justify-start lg:px-3",
      )}
    >
      <Icon className="size-[18px] shrink-0" aria-hidden="true" />
      <span className={cn("truncate", variant === "sidebar" && "sr-only lg:not-sr-only")}>{label}</span>
    </Link>
  );

  if (variant !== "sidebar") return link;
  // Rail (md) shows the label in a tooltip; on lg the label is visible.
  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side={dir === "rtl" ? "left" : "right"} className="lg:hidden">
        {label}
      </TooltipContent>
    </Tooltip>
  );
}

function UserMenu() {
  const { t } = useTranslation(["common", "auth"]);
  const language = useLanguage();
  const me = useCurrentUser();
  const logout = useLogout();
  const navigate = useNavigate();
  if (!me) return null;
  const name = pickName({ ar: me.full_name_ar, en: me.full_name_en }, language) || me.username;

  const onLogout = () => {
    logout.mutate(undefined, {
      onSettled: () => {
        toast.success(t("auth:logout.success"));
        void navigate({ to: "/login", replace: true });
      },
    });
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          className="h-10 gap-2 px-1.5 lg:px-2"
          aria-label={t("user.menu")}
          data-testid="user-menu"
        >
          <Avatar className="size-8">
            <AvatarFallback className="text-xs">{initials(name)}</AvatarFallback>
          </Avatar>
          <span className="hidden max-w-36 truncate text-sm font-medium xl:inline">{name}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="flex flex-col gap-1.5 py-2">
          <span className="text-xs font-normal text-muted">{t("user.signedInAs")}</span>
          <span className="truncate text-sm font-semibold text-fg">{name}</span>
          <span className="truncate text-xs font-normal text-muted" dir="ltr">
            {me.username}
          </span>
          {me.roles.length > 0 ? (
            <span className="flex flex-wrap gap-1 pt-1">
              {me.roles.map((role) => (
                <Badge key={role} variant="soft" className="text-[11px]">
                  {isKnownRole(role) ? t(`roles.${role}`) : role}
                </Badge>
              ))}
            </span>
          ) : null}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to="/change-password">
            <KeyRound />
            {t("user.changePassword")}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link to="/design">
            <Palette />
            {t("user.designSystem")}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onSelect={onLogout} data-testid="logout">
          <LogOut />
          {t("user.logout")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function CommandMenu({
  open,
  onOpenChange,
  items,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: readonly NavItem[];
}) {
  const { t } = useTranslation(["common", "nav"]);
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("search.open")}
      description={t("search.commandPlaceholder")}
    >
      <CommandInput placeholder={t("search.commandPlaceholder")} />
      <CommandList>
        <CommandEmpty>{t("search.noResults")}</CommandEmpty>
        <CommandGroup heading={t("search.pages")}>
          {items.map((item) => {
            const Icon = item.icon;
            const label = t(`nav:items.${item.labelKey}`);
            return (
              <CommandItem
                key={item.id}
                value={`${label} ${item.to}`}
                onSelect={() => {
                  onOpenChange(false);
                  void navigate({ to: item.to });
                }}
              >
                <Icon />
                <span className="flex-1">{label}</span>
                {pathname === item.to ? <span className="size-1.5 rounded-full bg-primary" aria-hidden="true" /> : null}
              </CommandItem>
            );
          })}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
