-- For an EXISTING database created from the old 01_schema.sql (fresh volumes already get this from 01_schema.sql).
-- Run outside an explicit transaction block:
--   docker compose exec -T db psql -U sms_user -d subscription_db < 04_migrate_subscription_status.sql
ALTER TYPE subscription_status ADD VALUE IF NOT EXISTS 'quotation' BEFORE 'active';
ALTER TYPE subscription_status ADD VALUE IF NOT EXISTS 'confirmed' BEFORE 'active';
