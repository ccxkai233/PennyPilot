-- PennyPilot database bootstrap. Application migrations own table creation.
-- pgcrypto provides gen_random_uuid() for UUID primary keys.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
