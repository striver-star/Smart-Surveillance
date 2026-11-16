-- Release 2.0: the monthly compliance and privacy report is archived with the other reports.
ALTER TABLE reports DROP CONSTRAINT IF EXISTS reports_kind_check;
ALTER TABLE reports ADD CONSTRAINT reports_kind_check CHECK (kind IN ('daily', 'weekly', 'monthly', 'custom', 'compliance'));
