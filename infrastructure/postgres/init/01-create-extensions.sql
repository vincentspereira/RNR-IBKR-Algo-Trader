-- Enable required PostgreSQL extensions
-- File: 01-create-extensions.sql

-- UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Cryptographic functions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Vector similarity search (pgvector)
CREATE EXTENSION IF NOT EXISTS "vector";

-- Verify extensions are installed
SELECT 
    extname AS extension_name,
    extversion AS version
FROM pg_extension 
WHERE extname IN ('uuid-ossp', 'pgcrypto', 'vector')
ORDER BY extname;
