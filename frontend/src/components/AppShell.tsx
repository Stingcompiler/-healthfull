import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { KeyRound, LogOut, Menu, PanelLeftClose, PanelLeftOpen, Palette, Search } from "lucide-react";
import { useCallback, useMemo, useState, type ComponentType, type ReactNode } from "react";
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
import { useBreakpoint } from "@/lib/hooks/use-media-query";
import { useShortcut } from "@/lib/hooks/use-shortcut";
import { useDirection, useLanguage } from "@/lib/i18n-hooks";
import { initials, pickName } from "@/lib/names";
import { cacheRailExpanded, readRailExpanded } from "@/lib/preferences";
import { cn } from "@/lib/utils";

const SEARCH_SHORTCUT = "mod+k";
/** Phone tab bar cells: up to this many modules, otherwise four modules plus "More". */
const TAB_BAR_CELLS = 5;

/** Records the quick search (Ctrl/⌘+K) finds besides pages, e.g. patient files (FEATURES 0.9). */
export interface QuickSearchSource {
  /** Renders `CommandGroup`s for the typed text; `onDone` closes the menu after a pick. */
  Results: ComponentType<{ query: string; onDone: () => void }>;
  /** Top-bar trigger text, e.g. "Search patients or pages…". */
  triggerLabel: string;
  /** Placeholder of the command input. */
  placeholder: string;
}

export interface AppShellProps {
  /** Navigation entries the current user may see (already permission-filtered). */
  nav: readonly NavItem[];
  /** Replaces the default quick-search trigger in the top bar. */
  search?: ReactNode;
  /** Extra records the quick search finds (patients); without it only pages are searched. */
  quickSearch?: QuickSearchSource;
  children: ReactNode;
}

/**
 * Authenticated layout.
 *   >= lg  full sidebar with group headings
 *   md     icon rail with tooltips, expandable to the labelled sidebar by a toggle (touch
 *          tablets have no hover); the choice is remembered on the device
 *   < md   top bar with drawer menu + bottom navigation
 */
export function AppShell({ nav, search, quickSearch, children }: AppShellProps) {
  const { t } = useTranslation(["common", "nav"]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const [railExpanded, setRailExpanded] = useState(readRailExpanded);
  const isLarge = useBreakpoint("lg");
  const labelled = isLarge || railExpanded;
  const toggleRail = useCallback(() => {
    setRailExpanded((expanded) => {
      cacheRailExpanded(!expanded);
      return !expanded;
    });
  }, []);
  const listed = useMemo(() => nav.filter((item) => !item.hidden), [nav]);
  // All modules when they fit the tab bar; otherwise the first four and "More" (the drawer).
  const needsMore = listed.length > TAB_BAR_CELLS;
  const bottomItems = needsMore ? listed.slice(0, TAB_BAR_CELLS - 1) : listed;
  const bottomCells = bottomItems.length + (needsMore ? 1 : 0);

  // ⌘K on macOS; Ctrl+K everywhere (most clinic PCs run Windows).
  // Also inside the palette itself (a dialog), so the same keys close it.
  useShortcut(
    [SEARCH_SHORTCUT, "ctrl+k"],
    () => {
      setCommandOpen((open) => !open);
    },
    { allowInDialogs: true },
  );

  return (
    <div className="min-h-dvh bg-bg">
      <a
        href="#main"
        className="sr-only z-[60] rounded-control bg-primary text-primary-fg focus:not-sr-only focus:fixed focus:start-4 focus:top-4 focus:inline-flex focus:min-h-11 focus:items-center focus:px-4"
      >
        {t("a11y.skipToContent")}
      </a>

      {/* Sidebar (lg, or md expanded) / rail (md) */}
      <aside
        data-slot="app-sidebar"
        data-labelled={labelled || undefined}
        className={cn(
          "fixed inset-y-0 start-0 z-30 hidden flex-col border-e border-border bg-surface md:flex",
          labelled ? "w-64" : "w-[72px]",
        )}
      >
        <div
          className={cn(
            "flex h-16 shrink-0 items-center border-b border-border",
            labelled ? "justify-start px-5" : "justify-center px-3",
          )}
        >
          <Link to="/" className="rounded-control focus-ring">
            {labelled ? <Brand /> : <BrandMark />}
          </Link>
        </div>
        <nav
          id="app-sidebar-nav"
          aria-label={t("a11y.mainNavigation")}
          className={cn("flex-1 scrollbar-thin overflow-y-auto py-2", labelled ? "px-3" : "px-2")}
        >
          <NavGroups items={listed} variant="sidebar" labelled={labelled} />
        </nav>
        {isLarge ? null : (
          <div className="shrink-0 border-t border-border p-2">
            <button
              type="button"
              onClick={toggleRail}
              aria-expanded={railExpanded}
              aria-controls="app-sidebar-nav"
              aria-label={railExpanded ? undefined : t("nav:shell.expandMenu")}
              data-testid="rail-toggle"
              className={cn(
                "flex h-11 w-full items-center gap-3 rounded-control text-sm font-medium text-muted transition-colors",
                "focus-ring-inset hover:bg-accent hover:text-fg",
                railExpanded ? "px-3" : "justify-center",
              )}
            >
              {railExpanded ? (
                <PanelLeftClose className="size-[18px] shrink-0 rtl:-scale-x-100" aria-hidden="true" />
              ) : (
                <PanelLeftOpen className="size-[18px] shrink-0 rtl:-scale-x-100" aria-hidden="true" />
              )}
              {railExpanded ? <span className="truncate">{t("nav:shell.collapseMenu")}</span> : null}
            </button>
          </div>
        )}
      </aside>

      <div className={cn("flex min-h-dvh min-w-0 flex-col", labelled ? "md:ps-64" : "md:ps-[72px]")}>
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
          <Link
            to="/"
            className="inline-flex size-11 shrink-0 items-center justify-center rounded-control focus-ring md:hidden"
            aria-label={t("appName")}
          >
            <BrandMark className="size-8" />
          </Link>
          <div className="flex min-w-0 flex-1 items-center">
            {search ?? (
              <QuickSearchTrigger
                label={quickSearch?.triggerLabel}
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
        {/* As many cells as items: a role with two modules gets two wide tabs, not two of five. */}
        <ul
          className="mx-auto grid h-16 max-w-md"
          style={{ gridTemplateColumns: `repeat(${String(Math.max(bottomCells, 1))}, minmax(0, 1fr))` }}
        >
          {bottomItems.map((item) => (
            <li key={item.id} className="min-w-0">
              <NavLink item={item} variant="bottom" />
            </li>
          ))}
          {needsMore ? (
            <li className="min-w-0">
              <button
                type="button"
                onClick={() => {
                  setDrawerOpen(true);
                }}
                data-testid="nav-more"
                className="group flex h-full w-full flex-col items-center justify-center gap-0.5 text-[11px] font-medium text-muted focus-ring-inset hover:text-fg"
              >
                <span className="flex h-7 w-12 items-center justify-center rounded-full">
                  <Menu className="size-5" aria-hidden="true" />
                </span>
                <span className="max-w-full truncate px-0.5">{t("nav:shell.more")}</span>
              </button>
            </li>
          ) : null}
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

      <CommandMenu open={commandOpen} onOpenChange={setCommandOpen} items={nav} source={quickSearch} />
    </div>
  );
}

function QuickSearchTrigger({ onOpen, label }: { onOpen: () => void; label?: string }) {
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
          "focus-ring transition-colors hover:border-border-strong hover:bg-surface",
        )}
      >
        <Search className="size-4 shrink-0" aria-hidden="true" />
        <span className="flex-1 truncate text-start">{label ?? t("search.globalPlaceholder")}</span>
        <KbdCombo combo={SEARCH_SHORTCUT} />
      </button>
    </>
  );
}

type NavVariant = "sidebar" | "drawer" | "bottom";

function NavGroups({
  items,
  variant,
  labelled = true,
  onNavigate,
}: {
  items: readonly NavItem[];
  variant: Exclude<NavVariant, "bottom">;
  /** Sidebar only: labels and group headings visible (lg, or the expanded tablet rail). */
  labelled?: boolean;
  onNavigate?: () => void;
}) {
  const { t } = useTranslation("nav");
  const showHeadings = variant === "drawer" || labelled;
  return (
    // Compact rhythm in the sidebar so every group fits a 1280x800 / 1366x768 screen.
    <div className={cn("flex flex-col", variant === "sidebar" ? "gap-2.5" : "gap-5")}>
      {NAV_GROUP_ORDER.map((group) => {
        const groupItems = items.filter((item) => item.group === group);
        if (groupItems.length === 0) return null;
        return (
          <div key={group} className="flex flex-col gap-0.5">
            {showHeadings ? (
              <div className="px-3 pb-0.5 text-[11px] leading-5 font-semibold tracking-wide text-muted uppercase">
                {t(`groups.${group}`)}
              </div>
            ) : (
              <div className="mx-auto mb-1 h-px w-6 bg-border" aria-hidden="true" />
            )}
            <ul className="flex flex-col gap-0.5">
              {groupItems.map((item) => (
                <li key={item.id}>
                  <NavLink item={item} variant={variant} labelled={labelled} onNavigate={onNavigate} />
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

function NavLink({
  item,
  variant,
  labelled = true,
  onNavigate,
}: {
  item: NavItem;
  variant: NavVariant;
  labelled?: boolean;
  onNavigate?: () => void;
}) {
  const { t } = useTranslation("nav");
  const dir = useDirection();
  const Icon = item.icon;
  const label = t(`items.${item.labelKey}`);
  const iconFlip = item.flipInRtl ? "rtl:-scale-x-100" : undefined;

  if (variant === "bottom") {
    // Phone tab bar: five cells of ~72px at 360px width, so it uses the short label
    // (nav:short, e.g. "Bookings" for "Appointments") and keeps the full one as a tooltip.
    return (
      // Active tab: not by color alone (WCAG 1.4.1): a tinted pill behind the icon and a bold label.
      <Link
        to={item.to}
        activeOptions={{ exact: item.exact ?? false }}
        data-testid={`nav-${item.id}`}
        title={label}
        className={cn(
          "group flex h-full flex-col items-center justify-center gap-0.5 text-[11px] font-medium text-muted transition-colors",
          "focus-ring-inset hover:text-fg",
          "data-[status=active]:font-bold data-[status=active]:text-primary-strong",
        )}
      >
        <span className="flex h-7 w-12 items-center justify-center rounded-full transition-colors group-data-[status=active]:bg-primary-soft">
          <Icon className={cn("size-5", iconFlip)} aria-hidden="true" />
        </span>
        <span data-slot="nav-label" className="max-w-full truncate px-0.5">
          {t(`short.${item.labelKey}`)}
        </span>
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
        "group flex items-center gap-3 rounded-control px-3 text-sm font-medium text-muted transition-colors",
        // Drawer (phones): 44px targets. Sidebar (mouse first): compact so every group fits.
        variant === "drawer" ? "h-11" : "h-9",
        "focus-ring-inset hover:bg-accent hover:text-fg",
        "data-[status=active]:bg-primary-soft data-[status=active]:text-primary-strong",
        variant === "sidebar" && !labelled && "h-10 justify-center px-0",
      )}
    >
      <Icon className={cn("size-[18px] shrink-0", iconFlip)} aria-hidden="true" />
      <span className={cn("truncate", variant === "sidebar" && !labelled && "sr-only")}>{label}</span>
    </Link>
  );

  if (variant !== "sidebar" || labelled) return link;
  // Collapsed rail (md): the label is a tooltip on hover/focus; touch users expand the rail.
  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side={dir === "rtl" ? "left" : "right"}>{label}</TooltipContent>
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
        {/* The accessible name contains the visible name (WCAG 2.5.3 Label in Name). */}
        <Button
          variant="ghost"
          className="h-11 gap-2 px-1.5 md:h-10 lg:px-2"
          aria-label={t("user.menuFor", { name })}
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
          <LogOut className="rtl:-scale-x-100" />
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
  source,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: readonly NavItem[];
  source?: QuickSearchSource;
}) {
  const { t } = useTranslation(["common", "nav"]);
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const [query, setQuery] = useState("");
  const placeholder = source?.placeholder ?? t("search.commandPlaceholder");
  const Results = source?.Results;
  const changeOpen = (next: boolean) => {
    if (!next) setQuery("");
    onOpenChange(next);
  };
  return (
    <CommandDialog open={open} onOpenChange={changeOpen} title={t("search.open")} description={placeholder}>
      <CommandInput placeholder={placeholder} value={query} onValueChange={setQuery} />
      <CommandList>
        <CommandEmpty>{t("search.noResults")}</CommandEmpty>
        {Results ? (
          <Results
            query={query}
            onDone={() => {
              changeOpen(false);
            }}
          />
        ) : null}
        <CommandGroup heading={t("search.pages")}>
          {items.map((item) => {
            const Icon = item.icon;
            const label = t(`nav:items.${item.labelKey}`);
            return (
              <CommandItem
                key={item.id}
                value={`${label} ${item.to}`}
                onSelect={() => {
                  changeOpen(false);
                  void navigate({ to: item.to });
                }}
              >
                <Icon className={item.flipInRtl ? "rtl:-scale-x-100" : undefined} />
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
