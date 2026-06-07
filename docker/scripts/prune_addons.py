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
    "hr_expense",
    "hr_timesheet",
    "hr_skills",
    "hr_work_entry_holidays",
    "hr_fleet",
    "hr_work_entry",
    "fleet",
    "website",
    "theme_default",
}

# Framework helpers pulled in automatically as transitive deps.
EXTRA_INSTALLABLE_MODULES: set[str] = {
    "base_import",
    "hr_calendar",
    "iap",
    "base_vat",
    "link_tracker",
    "base_address_extended",
    "website_hr_recruitment",
    "l10n_us",
    "spreadsheet_dashboard",
}

# These are in REQUESTED_MODULES but absent from Community CE image.
# Build does NOT fail if they are missing.
OPTIONAL_REQUESTED_MODULES: set[str] = {
    "hr_contract",
    "hr_payroll",
    "theme_default",
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
    "hr_expense",
    "hr_timesheet",
    "hr_skills",
    "hr_work_entry_holidays",
    "website",
    "hr_fleet",
    "hr_work_entry",
    "fleet",
    
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

def patch_base_module(base_dst: Path) -> None:
    """
    Fix Odoo 19 nightly-build data inconsistency: ir_module_module.xml can
    reference category XML IDs (base.module_category_xxx) that don't exist yet
    in ir_module_category_data.xml, causing a fatal ParseError on first boot.

    Strategy: diff the two files, inject minimal stub <record> entries for every
    missing ID so all refs resolve cleanly. Stubs are invisible in the UI.
    This runs at image build time so the fix survives restarts and DB restores.
    """
    category_file = base_dst / 'data' / 'ir_module_category_data.xml'
    module_file   = base_dst / 'data' / 'ir_module_module.xml'

    if not (category_file.exists() and module_file.exists()):
        return

    cat_text = category_file.read_text(encoding='utf-8')
    mod_text = module_file.read_text(encoding='utf-8')

    # IDs already defined in the category file (bare, no module prefix)
    defined_ids: set[str] = set(re.findall(r'<record[^>]+\bid="([^"]+)"', cat_text))

    # Every category ref used in ir_module_module.xml
    # e.g.  <field name="category_id" ref="base.module_category_services_timesheets"/>
    needed_ids: set[str] = {
        ref.split('.', 1)[-1]                          # strip leading "base."
        for ref in re.findall(
            r'<field\s+name="category_id"\s+ref="([^"]+)"', mod_text
        )
    }

    missing = needed_ids - defined_ids
    if not missing:
        return

    print(
        f'[prune_addons] Injecting {len(missing)} missing category stub(s) '
        f'into ir_module_category_data.xml: {sorted(missing)}',
        file=sys.stderr,
    )

    stubs: list[str] = []
    for cat_id in sorted(missing):
        # Derive a display name from the last underscore-segment
        raw  = cat_id.replace('module_category_', '')
        name = raw.rsplit('_', 1)[-1].capitalize()   # "timesheets" → "Timesheets"

        # Try to infer a parent from the ID (services_timesheets → services)
        parts     = raw.split('_')
        parent_id = 'module_category_' + '_'.join(parts[:-1]) if len(parts) > 1 else ''

        lines = [
            f'    <record id="{cat_id}" model="ir.module.category">',
            f'        <field name="name">{name}</field>',
        ]
        if parent_id and parent_id in defined_ids:
            lines.append(f'        <field name="parent_id" ref="{parent_id}"/>')
        lines += [
            '        <field name="visible" eval="False"/>',
            '    </record>',
        ]
        stubs.append('\n'.join(lines))

    category_file.write_text(
        cat_text.replace('</odoo>', '\n' + '\n\n'.join(stubs) + '\n</odoo>'),
        encoding='utf-8',
    )
    print('[prune_addons] ir_module_category_data.xml patched successfully.', file=sys.stderr)

def patch_pruned_module_refs(target_addons: Path, installable: set[str]) -> None:
    """
    Scan every *.xml data file under target_addons.  For each <record> block
    that contains  ref="base.module_XXX"  where XXX is a pruned (non-installable)
    module, inject  forcecreate="0"  on the opening <record> tag.

    With forcecreate="0":
      • New record (ID not yet in ir.model.data) → silently skipped.
      • Existing record → updated; missing refs resolve to False instead of
        raising ValueError.
    Both outcomes are safe: the record concerns a module we deliberately removed.

    Typical targets: website.configurator.feature, ir.module.module records,
    any data file that ships "optional companion" module references.
    """
    ref_re = re.compile(r'\bref="base\.module_([A-Za-z0-9_]+)"')
    patched_files: list[str] = []

    for xml_path in sorted(target_addons.rglob('*.xml')):
        text = xml_path.read_text(encoding='utf-8')
        if 'base.module_' not in text:
            continue

        # Quick pre-filter: any ref in this file points to a pruned module?
        file_module_refs = set(ref_re.findall(text))
        if not (file_module_refs - installable):
            continue

        # Split on </record> — Odoo data files never nest <record> elements,
        # so each chunk is exactly one record's opening tag + body.
        chunks = text.split('</record>')
        changed = False
        out: list[str] = []

        for chunk in chunks[:-1]:
            block_refs = set(ref_re.findall(chunk))
            if block_refs - installable:
                # Stamp forcecreate="0" on the <record …> opening tag.
                chunk = re.sub(
                    r'<record\b[^>]*>',
                    lambda m: (
                        m.group().replace('<record', '<record forcecreate="0"', 1)
                        if 'forcecreate' not in m.group()
                        else m.group()
                    ),
                    chunk,
                    count=1,
                )
                changed = True
            out.append(chunk)
        out.append(chunks[-1])

        if changed:
            xml_path.write_text('</record>'.join(out), encoding='utf-8')
            patched_files.append(str(xml_path.relative_to(target_addons)))

    if patched_files:
        print(
            f'[prune_addons] forcecreate="0" stamped on pruned-module-ref '
            f'records in {len(patched_files)} file(s):\n  '
            + '\n  '.join(patched_files),
            file=sys.stderr,
        )

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
    patch_base_module(TARGET_ADDONS / 'base')   # ← ADD THIS LINE
    patch_pruned_module_refs(TARGET_ADDONS, installable)   # ← ADD THIS
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