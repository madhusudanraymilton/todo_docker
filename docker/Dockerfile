# syntax=docker/dockerfile:1.6
#
# Odoo 19 image with a curated bundled-addon surface:
#   /mnt/core         selected Odoo core/HR modules + dependency closure
#   /mnt/extra-addons user custom addons

FROM odoo:19.0

LABEL maintainer="ZenCore DevOps <devops@zencore.local>"
LABEL org.opencontainers.image.title="odoo19-curated"
LABEL org.opencontainers.image.description="Odoo 19 limited to curated core, HR, and custom addons"

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

USER root

COPY scripts/prune_addons.py /tmp/prune_addons.py
RUN python3 /tmp/prune_addons.py \
    && rm -f /tmp/prune_addons.py

COPY scripts/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY scripts/lock_modules.sql /opt/lock_modules.sql

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/lib/python3/dist-packages/odoo/addons \
    && ln -s /mnt/core /usr/lib/python3/dist-packages/odoo/addons \
    && rm -rf /usr/lib/python3/dist-packages/addons \
    && mkdir -p /usr/lib/python3/dist-packages/addons \
    && mkdir -p /mnt/extra-addons /var/log/odoo \
    # FIX 1: Strip Windows line endings (\r\n → \n).
    # Without this, the shebang becomes "#!/usr/bin/env bash\r" — interpreter
    # not found — kernel falls back to /bin/sh (dash), which doesn't support
    # pipefail, causing the container to crash-loop immediately.
    && sed -i 's/\r//' /usr/local/bin/entrypoint.sh \
    && chmod 0755 /usr/local/bin/entrypoint.sh \
    && chown -R odoo:odoo /mnt/core /mnt/extra-addons /var/log/odoo \
        /opt/odoo-installable-modules.txt /opt/odoo-app-modules.txt /opt/lock_modules.sql

USER odoo

EXPOSE 8069 8072

# FIX 2: Explicitly invoke /bin/bash instead of relying on shebang+exec.
# ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]  ← old: depends on shebang working
# The exec form with bash explicitly bypasses all shebang/permission edge cases.
ENTRYPOINT ["/bin/bash", "/usr/local/bin/entrypoint.sh"]
CMD ["odoo"]
