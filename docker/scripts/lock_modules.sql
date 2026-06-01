-- ============================================================================
-- lock_modules.sql
-- ----------------------------------------------------------------------------
-- Runs on every boot after the database has an Odoo schema.
--
-- Purpose:
--   * /mnt/core contains only curated bundled addons copied at image build time.
--   * /mnt/extra-addons contains your custom addons.
--   * This SQL is a defense-in-depth database lock for restored databases or
--     records created before the policy existed.
--
-- The entrypoint replaces:
--   __INSTALLABLE_PLACEHOLDER__ with dependency-safe module names.
--   __APP_PLACEHOLDER__         with modules allowed to appear as Apps.
-- ============================================================================

BEGIN;

-- Hide every module outside the installable policy.
UPDATE ir_module_module
   SET application  = FALSE,
       auto_install = FALSE
 WHERE name NOT IN (__INSTALLABLE_PLACEHOLDER__);

-- Force every non-whitelisted, not-yet-installed module into uninstallable.
-- Installed legacy modules are not auto-removed because that can destroy data.
UPDATE ir_module_module
   SET state = 'uninstallable'
 WHERE name NOT IN (__INSTALLABLE_PLACEHOLDER__)
   AND state IN ('uninstalled', 'to install', 'to upgrade');

-- Restore curated modules that may have been locked by an older policy.
UPDATE ir_module_module
   SET state = 'uninstalled'
 WHERE name IN (__INSTALLABLE_PLACEHOLDER__)
   AND state = 'uninstallable';

-- Dependency helper modules stay installable but do not appear as Apps unless
-- explicitly requested or provided as custom addons.
UPDATE ir_module_module
   SET application = FALSE
 WHERE name IN (__INSTALLABLE_PLACEHOLDER__)
   AND name NOT IN (__APP_PLACEHOLDER__);

-- Optional hard policy for legacy databases:
--
-- UPDATE ir_module_module
--    SET state = 'to remove'
--  WHERE name NOT IN (__INSTALLABLE_PLACEHOLDER__)
--    AND state = 'installed';

DO $$
DECLARE
    locked_count  INT;
    visible_count INT;
BEGIN
    SELECT COUNT(*) INTO locked_count
      FROM ir_module_module
     WHERE state = 'uninstallable';

    SELECT COUNT(*) INTO visible_count
      FROM ir_module_module
     WHERE state <> 'uninstallable'
       AND application IS TRUE;

    RAISE NOTICE '[lock_modules] uninstallable hidden modules: %', locked_count;
    RAISE NOTICE '[lock_modules] visible application modules: %', visible_count;
END $$;

COMMIT;
