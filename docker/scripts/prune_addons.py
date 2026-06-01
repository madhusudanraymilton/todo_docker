# #!/usr/bin/env python3
# """Build a curated /mnt/core addons tree for the custom Odoo image.

# The official image ships every Community addon under Odoo's Python package.
# This script copies only the requested modules and their manifest dependency
# closure into /mnt/core, then writes two policy files consumed by entrypoint.sh:

# * /opt/odoo-installable-modules.txt: dependency-safe modules allowed to install.
# * /opt/odoo-app-modules.txt: modules allowed to remain visible as Apps.

# Custom addons under /mnt/extra-addons are discovered at runtime and appended to
# both policies by entrypoint.sh.
# """

# from __future__ import annotations

# import os
# import shutil
# import sys
# from pathlib import Path
# from ast import literal_eval

# SOURCE_ADDONS = Path("/usr/lib/python3/dist-packages/odoo/addons")
# TARGET_ADDONS = Path("/mnt/core")

# REQUESTED_MODULES: set[str] = {
#     "base",
#     "web",
#     "mail",
#     "resource",
#     "hr",
#     "hr_attendance",
#     "hr_holidays",
#     "hr_recruitment",
#     "hr_contract",
#     "hr_payroll",
# }

# # Useful framework helpers that are safe to expose to dependency resolution.
# # base_import is not a requested app, but it preserves normal import UX.
# EXTRA_INSTALLABLE_MODULES: set[str] = {
#     "base_import",
#     "hr_calendar",
#     "iap",
# }

# # These modules are requested but are not present in the official Community
# # image used locally. Keep the build usable; they become installable if supplied
# # later through /mnt/extra-addons or a private base image.
# OPTIONAL_REQUESTED_MODULES: set[str] = {
#     "hr_contract",
#     "hr_payroll",
# }

# VISIBLE_APP_MODULES: set[str] = REQUESTED_MODULES


# def read_manifest(module: str) -> dict:
#     manifest = SOURCE_ADDONS / module / "__manifest__.py"
#     return literal_eval(manifest.read_text(encoding="utf-8"))


# def dependency_closure(seed_modules: set[str]) -> tuple[set[str], set[str]]:
#     installable: set[str] = set()
#     missing: set[str] = set()

#     def visit(module: str) -> None:
#         if module in installable:
#             return

#         manifest_path = SOURCE_ADDONS / module / "__manifest__.py"
#         if not manifest_path.exists():
#             missing.add(module)
#             return

#         manifest = read_manifest(module)
#         for dep in manifest.get("depends", []):
#             visit(dep)
#         installable.add(module)

#     for module in sorted(seed_modules):
#         visit(module)

#     return installable, missing


# def ignore_noise(_directory: str, names: list[str]) -> set[str]:
#     return {
#         name
#         for name in names
#         if name == "__pycache__" or name.endswith((".pyc", ".pyo"))
#     }


# def copy_curated_modules(modules: set[str]) -> None:
#     if TARGET_ADDONS.exists():
#         shutil.rmtree(TARGET_ADDONS)
#     TARGET_ADDONS.mkdir(parents=True, exist_ok=True)

#     for module in sorted(modules):
#         src = SOURCE_ADDONS / module
#         dst = TARGET_ADDONS / module
#         shutil.copytree(src, dst, symlinks=True, ignore=ignore_noise)


# def write_policy(path: str, modules: set[str]) -> None:
#     with open(path, "w", encoding="utf-8") as fh:
#         for module in sorted(modules):
#             fh.write(module + "\n")


# def main() -> int:
#     if not SOURCE_ADDONS.is_dir():
#         print(f"[module_policy] ERROR: {SOURCE_ADDONS} not found", file=sys.stderr)
#         return 1

#     installable, missing = dependency_closure(REQUESTED_MODULES | EXTRA_INSTALLABLE_MODULES)
#     hard_missing = missing - OPTIONAL_REQUESTED_MODULES
#     optional_missing = missing & OPTIONAL_REQUESTED_MODULES

#     if hard_missing:
#         print(f"[module_policy] ERROR: required modules missing: {sorted(hard_missing)}", file=sys.stderr)
#         return 1

#     if optional_missing:
#         print(
#             "[module_policy] WARNING: optional requested modules missing from "
#             f"Community image: {sorted(optional_missing)}",
#             file=sys.stderr,
#         )

#     copy_curated_modules(installable)
#     write_policy("/opt/odoo-installable-modules.txt", installable)
#     write_policy("/opt/odoo-app-modules.txt", VISIBLE_APP_MODULES)

#     print(f"[module_policy] copied {len(installable)} modules to {TARGET_ADDONS}")
#     print(f"[module_policy] installable: {', '.join(sorted(installable))}")
#     print(f"[module_policy] visible apps policy: {', '.join(sorted(VISIBLE_APP_MODULES))}")
#     return 0


# if __name__ == "__main__":
#     sys.exit(main())
#!/usr/bin/env python3
"""Build a curated /mnt/core addons tree for the custom Odoo image.

The official image ships every Community addon under Odoo's Python package.
This script:
  1. Resolves the dependency closure of REQUESTED_MODULES.
  2. Copies only those modules to /mnt/core.
  3. PATCHES dependency-only module manifests to force 'application': False on disk.
     → This is the PRIMARY defense. Odoo's ir.module.module.update_list() reads
       manifests from the filesystem. Patching here means even if a user clicks
       "Update Apps List", the manifests already say application=False.
  4. Writes policy files consumed by entrypoint.sh for the SQL defense-in-depth lock.
"""

from __future__ import annotations

import re
import shutil
import sys
from ast import literal_eval
from pathlib import Path

SOURCE_ADDONS = Path("/usr/lib/python3/dist-packages/odoo/addons")
TARGET_ADDONS = Path("/mnt/core")

# ── Modules you actually WANT installed / available ──────────────────────────
REQUESTED_MODULES: set[str] = {
    "base",
    "web",
    "mail",
    "resource",
    "hr",
    "hr_attendance",
    "hr_holidays",
    "hr_recruitment",
    "hr_contract",   # Enterprise-only; safe to list here, handled by OPTIONAL below
    "hr_payroll",    # Enterprise-only; same
}

# Framework helpers pulled in automatically as transitive deps.
EXTRA_INSTALLABLE_MODULES: set[str] = {
    "base_import",
    "hr_calendar",
    "iap",
}

# These are in REQUESTED_MODULES but absent from Community CE image.
# Build does NOT fail if they are missing.
OPTIONAL_REQUESTED_MODULES: set[str] = {
    "hr_contract",
    "hr_payroll",
}

# ── FIX #1 ───────────────────────────────────────────────────────────────────
# ONLY these modules appear in Odoo's Apps menu.
# Removed: base, web, mail, resource  (framework — not apps)
# Removed: hr_contract, hr_payroll    (Enterprise-only, absent in CE image)
VISIBLE_APP_MODULES: set[str] = {
    "hr",
    "hr_attendance",
    "hr_holidays",
    "hr_recruitment",
}
# To add more HR sub-apps (e.g. hr_timesheet, hr_org_chart) just append here.
# ─────────────────────────────────────────────────────────────────────────────


# ── Dependency resolution ─────────────────────────────────────────────────────

def read_manifest(module: str) -> dict:
    manifest = SOURCE_ADDONS / module / "__manifest__.py"
    return literal_eval(manifest.read_text(encoding="utf-8"))


def dependency_closure(seed_modules: set[str]) -> tuple[set[str], set[str]]:
    """Walk manifest 'depends' fields recursively; return (installable, missing)."""
    installable: set[str] = set()
    missing: set[str] = set()

    def visit(module: str) -> None:
        if module in installable or module in missing:
            return
        manifest_path = SOURCE_ADDONS / module / "__manifest__.py"
        if not manifest_path.exists():
            missing.add(module)
            return
        for dep in read_manifest(module).get("depends", []):
            visit(dep)
        installable.add(module)

    for module in sorted(seed_modules):
        visit(module)

    return installable, missing


# ── FIX #2: Manifest patching ─────────────────────────────────────────────────

def patch_manifest_application(module_dst: Path) -> bool:
    """
    Overwrite 'application': True → False in a copied __manifest__.py.

    WHY THIS IS THE REAL FIX:
      Odoo's ir.module.module.update_list() re-reads __manifest__.py from disk
      on every call (UI button "Update Apps List", or --update flag).
      Patching the file at image build time makes application=False permanent —
      it survives container restarts, DB restores, and UI update_list() calls.
      The SQL lock in lock_modules.sql is defense-in-depth only.

    Returns True when the file was actually modified.
    """
    manifest_path = module_dst / "__manifest__.py"
    if not manifest_path.exists():
        return False

    original = manifest_path.read_text(encoding="utf-8")

    # Handles both  'application': True  and  "application": True
    patched = re.sub(
        r"""(['"]application['"]\s*:\s*)True""",
        r"\g<1>False",
        original,
    )

    if patched == original:
        return False  # either already False, or key absent — nothing to do

    manifest_path.write_text(patched, encoding="utf-8")
    return True


# ── Copy + patch ──────────────────────────────────────────────────────────────

def ignore_noise(_directory: str, names: list[str]) -> set[str]:
    return {n for n in names if n == "__pycache__" or n.endswith((".pyc", ".pyo"))}


def copy_curated_modules(modules: set[str], app_modules: set[str]) -> None:
    if TARGET_ADDONS.exists():
        shutil.rmtree(TARGET_ADDONS)
    TARGET_ADDONS.mkdir(parents=True, exist_ok=True)

    patched: list[str] = []

    for module in sorted(modules):
        src = SOURCE_ADDONS / module
        dst = TARGET_ADDONS / module
        shutil.copytree(src, dst, symlinks=True, ignore=ignore_noise)

        if module not in app_modules:
            # Dependency-only module: patch manifest so it never shows as an App.
            if patch_manifest_application(dst):
                patched.append(module)

    if patched:
        print(
            f"[prune_addons] Patched {len(patched)} dependency manifests "
            f"(application=False): {', '.join(patched)}",
            file=sys.stderr,
        )


# ── Policy file writers ───────────────────────────────────────────────────────

def write_policy(path: str, modules: set[str]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for module in sorted(modules):
            fh.write(module + "\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    if not SOURCE_ADDONS.is_dir():
        print(f"[prune_addons] ERROR: source addons not found: {SOURCE_ADDONS}", file=sys.stderr)
        return 1

    installable, missing = dependency_closure(
        REQUESTED_MODULES | EXTRA_INSTALLABLE_MODULES
    )

    hard_missing = missing - OPTIONAL_REQUESTED_MODULES
    optional_missing = missing & OPTIONAL_REQUESTED_MODULES

    if hard_missing:
        print(
            f"[prune_addons] ERROR: required modules missing on disk: {sorted(hard_missing)}",
            file=sys.stderr,
        )
        return 1

    if optional_missing:
        print(
            "[prune_addons] WARNING: Enterprise-only modules absent from Community image "
            f"(expected): {sorted(optional_missing)}",
            file=sys.stderr,
        )

    # Guard: VISIBLE_APP_MODULES must be a subset of what actually exists on disk
    effective_app_modules = VISIBLE_APP_MODULES & installable
    ghost_apps = VISIBLE_APP_MODULES - installable
    if ghost_apps:
        print(
            f"[prune_addons] WARNING: VISIBLE_APP_MODULES not in installable, "
            f"ignored: {sorted(ghost_apps)}",
            file=sys.stderr,
        )

    copy_curated_modules(installable, effective_app_modules)
    write_policy("/opt/odoo-installable-modules.txt", installable)
    write_policy("/opt/odoo-app-modules.txt", effective_app_modules)

    print(f"[prune_addons] Kept ({len(installable)}): {', '.join(sorted(installable))}")
    print(
        f"[prune_addons] Visible app modules ({len(effective_app_modules)}): "
        f"{', '.join(sorted(effective_app_modules))}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())