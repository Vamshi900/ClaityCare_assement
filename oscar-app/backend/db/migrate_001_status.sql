-- Migration: Add status tracking and versioning
ALTER TABLE policies ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'discovered';
ALTER TABLE structured_policies ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE structured_policies ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT true;

-- Backfill status from existing data
UPDATE policies SET status = 'downloaded' WHERE EXISTS (SELECT 1 FROM downloads d WHERE d.policy_id = policies.id AND d.error IS NULL);
UPDATE policies SET status = 'validated' WHERE EXISTS (SELECT 1 FROM structured_policies sp WHERE sp.policy_id = policies.id AND sp.validation_error IS NULL);
UPDATE policies SET status = 'extracted' WHERE EXISTS (SELECT 1 FROM structured_policies sp WHERE sp.policy_id = policies.id AND sp.validation_error IS NOT NULL) AND status != 'validated';
UPDATE policies SET status = 'download_failed' WHERE EXISTS (SELECT 1 FROM downloads d WHERE d.policy_id = policies.id AND d.error IS NOT NULL) AND status = 'discovered';
