# Archiving Policy

**Effective:** 2026-05-29
**Authority:** Operator directive (Vincent S. Pereira)
**Status:** Binding for all remediation work

---

## The rule

A file may be moved to `.archive/` **only** when one of the following is true:

1. **Rewrite-first (default).** Its intended logic has been **completely
   rewritten** into a clean canonical location, the rewrite is tested, and the
   behaviour it provided is preserved or deliberately superseded. Only then is
   the original archived (as historical reference).

2. **Not-worth-it (documented exception).** A written recommendation explains
   why the file's logic does **not** warrant a rewrite (e.g. duplicate of an
   existing canonical implementation, abandoned approach, weak evidence base,
   superseded by a better design). The recommendation is recorded in a
   `*.rationale.md` next to the archived file **and** summarised in the relevant
   remediation memo.

**Never** archive a file purely to make a linter or the no-stubs hook pass.
Silent deletion of capability is prohibited.

## Applies to

Every file touched by Phase 0.5 remediation and any future cleanup: damaged
code, stubs, skeletons, duplicates, and superseded modules.

## Decision record per file

Each archived file carries a `<name>.rationale.md` stating:

- Original path
- Date archived
- Decision: `REWRITTEN` (with the path of the clean replacement) or
  `NOT_WORTH_REWRITING` (with the reason)
- For `REWRITTEN`: a one-line note on where the logic now lives and how it was
  verified (test file / coverage)

## Retroactive application

Files already archived in earlier sessions (engines, misplaced pillars) are
re-audited against this policy:

- **Misplaced pillars** -> NOT_WORTH_REWRITING: the canonical pillar
  implementation already exists at
  `core_trading/strategies/core/augmented_base_institutional_strategy.py`. The
  archived files were misnamed god-class extracts with no unique logic.
- **Engines** (smart-money, ai-signal, portfolio, etc.) -> these map to
  rewrites scheduled in Phases 5/6. Their archived copies serve as the **logic
  reference** for those rewrites. They will be reconstructed clean in their
  target phase; until then the archive is the source of intent. (Documented in
  each engine's existing rationale file.)

## Phase-deferred rewrites

Some damaged files are deliberately **not** rewritten now because doing so
correctly requires infrastructure that later phases build (e.g. quant strategy
skeletons need the Phase 2 feature store + Phase 3 backtest engine before they
can be rewritten and validated). These are:

- **Left in place** (not archived) until their phase, OR
- **Archived with a `NOT_WORTH_REWRITING_NOW` recommendation** that names the
  target phase, when leaving them in place would block a Definition-of-Done.

The choice between the two is recorded per file. Rewriting a strategy before its
validation harness exists would produce untested code, which violates the
no-stubs / tested-end-to-end principle — so deferral is the correct engineering
call, not a shortcut.
