ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS username varchar(40);

WITH normalized AS (
    SELECT
        id,
        COALESCE(
            NULLIF(
                regexp_replace(lower(split_part(email, '@', 1)), '[^a-z0-9._-]', '', 'g'),
                ''
            ),
            'admin'
        ) AS base
    FROM admin_users
),
duplicates AS (
    SELECT base, count(*) AS total
    FROM normalized
    GROUP BY base
)
UPDATE admin_users AS admin
SET username = CASE
    WHEN duplicates.total = 1 THEN left(normalized.base, 40)
    ELSE left(normalized.base, 30) || '_' || admin.id::text
END
FROM normalized
JOIN duplicates ON duplicates.base = normalized.base
WHERE admin.id = normalized.id
  AND admin.username IS NULL;

ALTER TABLE admin_users ALTER COLUMN username SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_admin_users_username_lowercase'
          AND conrelid = 'admin_users'::regclass
    ) THEN
        ALTER TABLE admin_users
            ADD CONSTRAINT ck_admin_users_username_lowercase
            CHECK (username = lower(username));
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_admin_users_username'
          AND conrelid = 'admin_users'::regclass
    ) THEN
        ALTER TABLE admin_users
            ADD CONSTRAINT uq_admin_users_username UNIQUE (username);
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS alembic_version (
    version_num varchar(32) NOT NULL PRIMARY KEY
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM alembic_version WHERE version_num = '0001'
    ) THEN
        UPDATE alembic_version SET version_num = '0002' WHERE version_num = '0001';
    ELSIF NOT EXISTS (SELECT 1 FROM alembic_version) THEN
        INSERT INTO alembic_version (version_num) VALUES ('0002');
    END IF;
END
$$;
