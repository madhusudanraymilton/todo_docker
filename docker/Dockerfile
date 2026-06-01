# syntax=docker/dockerfile:1.6
#
# Odoo 19 image with a curated bundled-addon surface:
#   /mnt/core         selected Odoo core/HR modules + dependency closure
#   /mnt/extra-addons user custom addons
#
# The upstream /usr/lib/python3/dist-packages/odoo/addons path is deliberately
# not used in addons_path, so Sales/CRM/Inventory/Accounting/etc. are not
# discoverable by Odoo.

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
    && chmod 0755 /usr/local/bin/entrypoint.sh \
    && chown -R odoo:odoo /mnt/core /mnt/extra-addons /var/log/odoo \
        /opt/odoo-installable-modules.txt /opt/odoo-app-modules.txt /opt/lock_modules.sql

USER odoo

EXPOSE 8069 8072

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["odoo"]
