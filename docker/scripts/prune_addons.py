#!/usr/bin/env python3
"""Build a curated /mnt/core addons tree for the custom Odoo image.

The official image ships every Community addon under Odoo's Python package.
This script copies only the requested modules and their manifest dependency
closure into /mnt/core, then writes two policy files consumed by entrypoint.sh:

* /opt/odoo-installable-modules.txt: dependency-safe modules allowed to install.
* /opt/odoo-app-modules.txt: modules allowed to remain visible as Apps.

Custom addons under /mnt/extra-addons are discovered at runtime and appended to
both policies by entrypoint.sh.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from ast import literal_eval

SOURCE_ADDONS = Path("/usr/lib/python3/dist-packages/odoo/addons")
TARGET_ADDONS = Path("/mnt/core")

REQUESTED_MODULES: set[str] = {
    "base",
    "web",
    "mail",
    "resource",
    "hr",
    "hr_attendance",
    "hr_holidays",
    "hr_recruitment",
    "hr_contract",
    "hr_payroll",
}

# Useful framework helpers that are safe to expose to dependency resolution.
# base_import is not a requested app, but it preserves normal import UX.
EXTRA_INSTALLABLE_MODULES: set[str] = {
    "base_import",
    "hr_calendar",
    "iap",
}

# These modules are requested but are not present in the official Community
# image used locally. Keep the build usable; they become installable if supplied
# later through /mnt/extra-addons or a private base image.
OPTIONAL_REQUESTED_MODULES: set[str] = {
    "hr_contract",
    "hr_payroll",
}

VISIBLE_APP_MODULES: set[str] = REQUESTED_MODULES


def read_manifest(module: str) -> dict:
    manifest = SOURCE_ADDONS / module / "__manifest__.py"
    return literal_eval(manifest.read_text(encoding="utf-8"))


def dependency_closure(seed_modules: set[str]) -> tuple[set[str], set[str]]:
    installable: set[str] = set()
    missing: set[str] = set()

    def visit(module: str) -> None:
        if module in installable:
            return

        manifest_path = SOURCE_ADDONS / module / "__manifest__.py"
        if not manifest_path.exists():
            missing.add(module)
            return

        manifest = read_manifest(module)
        for dep in manifest.get("depends", []):
            visit(dep)
        installable.add(module)

    for module in sorted(seed_modules):
        visit(module)

    return installable, missing


def ignore_noise(_directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name == "__pycache__" or name.endswith((".pyc", ".pyo"))
    }


def copy_curated_modules(modules: set[str]) -> None:
    if TARGET_ADDONS.exists():
        shutil.rmtree(TARGET_ADDONS)
    TARGET_ADDONS.mkdir(parents=True, exist_ok=True)

    for module in sorted(modules):
        src = SOURCE_ADDONS / module
        dst = TARGET_ADDONS / module
        shutil.copytree(src, dst, symlinks=True, ignore=ignore_noise)


def write_policy(path: str, modules: set[str]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for module in sorted(modules):
            fh.write(module + "\n")


def main() -> int:
    if not SOURCE_ADDONS.is_dir():
        print(f"[module_policy] ERROR: {SOURCE_ADDONS} not found", file=sys.stderr)
        return 1

    installable, missing = dependency_closure(REQUESTED_MODULES | EXTRA_INSTALLABLE_MODULES)
    hard_missing = missing - OPTIONAL_REQUESTED_MODULES
    optional_missing = missing & OPTIONAL_REQUESTED_MODULES

    if hard_missing:
        print(f"[module_policy] ERROR: required modules missing: {sorted(hard_missing)}", file=sys.stderr)
        return 1

    if optional_missing:
        print(
            "[module_policy] WARNING: optional requested modules missing from "
            f"Community image: {sorted(optional_missing)}",
            file=sys.stderr,
        )

    copy_curated_modules(installable)
    write_policy("/opt/odoo-installable-modules.txt", installable)
    write_policy("/opt/odoo-app-modules.txt", VISIBLE_APP_MODULES)

    print(f"[module_policy] copied {len(installable)} modules to {TARGET_ADDONS}")
    print(f"[module_policy] installable: {', '.join(sorted(installable))}")
    print(f"[module_policy] visible apps policy: {', '.join(sorted(VISIBLE_APP_MODULES))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
