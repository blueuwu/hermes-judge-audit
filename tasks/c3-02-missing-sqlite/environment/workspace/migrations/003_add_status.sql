-- 003: account status. Accounts on the retired old.example domain are disabled.
ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
CREATE INDEX idx_users_status ON users(status);
UPDATE users SET status = 'disabled' WHERE email LIKE '%@old.example';
UPDATE meta SET value = '3' WHERE key = 'schema_version';
