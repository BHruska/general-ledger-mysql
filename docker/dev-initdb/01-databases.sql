-- General Ledger v0.1.0
-- File: docker/dev-initdb/01-databases.sql
-- Description: Dev database bootstrap. Keep identical to the SQL the infra side
--              runs on the server (NEW-APP-INTEGRATION.md section 7), plus the
--              test database, so grants match production.
-- Runs only on the first start against an empty volume. To re-run:
--   docker compose -f compose.dev.yml down -v
CREATE DATABASE IF NOT EXISTS gl      CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS gl_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON gl.*      TO 'gl'@'%';
GRANT ALL PRIVILEGES ON gl_test.* TO 'gl'@'%';
