---
name: ship-feature
description: Build, test, review, fix, push, open PR, and merge a feature in hospital-sys following the project's modern delivery loop. Use whenever implementing any item from docs/FEATURES.md or any change destined for main.
---

# Ship a feature (build → test → review → fix → push → merge)

Follow every step. Do not skip review or tests to save time.

## 1. Build
- Start from an up-to-date `main`: `git switch main && git pull --ff-only` (skip pull if no remote).
- Branch: `git switch -c feat/<phase>-<slug>` (fix/ for bugs, chore/ for tooling).
- Read the relevant FEATURES.md items by number and the FLOW.md steps they touch.
- Test first for money, stock, state, or permission logic: write the failing domain/service test, then the code.
- Small Conventional Commits (`feat(billing): approve invoice freezes prices`), each leaving the tree buildable.

## 2. Test
Run and read the output of:
```
make check
make e2e E2E_GREP=<feature tag>
```
Every new or changed screen must pass the responsive matrix (3 viewports, 3 themes, 2 languages) and save screenshots to `artifacts/screens/`.

## 3. Review (self, adversarial)
Re-read the full diff (`git diff main...HEAD`) against this checklist and write findings down:
- [ ] Seven invariants in CLAUDE.md hold; DB triggers still protect frozen rows
- [ ] Every money/stock path has a Hypothesis or service test
- [ ] Permission check on every new endpoint; doctor has no billing access
- [ ] Audit context (user, reason) set on every write
- [ ] `select_for_update` where concurrent writes could race (shift, batch stock, allocation)
- [ ] API error codes are specific and translated in the `errors` namespace
- [ ] No hardcoded strings, raw colors, or physical left/right utilities
- [ ] Phone layout works; tables collapse to cards; no horizontal scroll
- [ ] ar/en key parity; RTL icons flip
- [ ] OpenAPI regenerated (`make api`) and committed
- [ ] No internet calls at runtime

## 4. Fix
Fix every finding, re-run step 2. Never weaken an invariant test; if a rule must change, add an ADR in `docs/adr/`.

## 5. Push and PR
```
git push -u origin HEAD
gh pr create --fill --base main
```
PR body: FEATURES.md item numbers, what changed, test results with counts, screenshots list, ADRs. End with the attribution line required by the session.

## 6. Merge
After CI is green: `gh pr merge --squash --delete-branch`, then `git switch main && git pull --ff-only`.
Without a remote: `git switch main && git merge --squash <branch> && git commit`.

## 7. Record
Update `CHANGELOG.md` (Unreleased section) and tick items in `PROGRESS.md`.
