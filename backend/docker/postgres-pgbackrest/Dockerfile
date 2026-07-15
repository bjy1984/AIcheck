ARG AICHECK_POSTGRES_BASE_IMAGE=pgvector/pgvector:pg16
FROM ${AICHECK_POSTGRES_BASE_IMAGE}

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        gnupg \
        jq \
        pgbackrest \
        python3 \
        python3-pip \
        python3-venv \
    && python3 -m venv /opt/aicheck-backup-venv \
    && /opt/aicheck-backup-venv/bin/pip install --no-cache-dir "minio>=7.2,<8" \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -o postgres -g postgres -m 0750 /var/log/pgbackrest /var/spool/pgbackrest

COPY docker/postgres-pgbackrest/pgbackrest.conf /etc/pgbackrest/pgbackrest.conf
COPY docker/postgres-pgbackrest/entrypoint.sh /usr/local/bin/aicheck-pgbackrest-entrypoint
COPY scripts/backup /opt/aicheck-backup

RUN chmod 0755 /usr/local/bin/aicheck-pgbackrest-entrypoint /opt/aicheck-backup/*.py /opt/aicheck-backup/*.sh \
    && chown root:postgres /etc/pgbackrest/pgbackrest.conf \
    && chmod 0640 /etc/pgbackrest/pgbackrest.conf

ENTRYPOINT ["aicheck-pgbackrest-entrypoint"]
CMD ["postgres"]
