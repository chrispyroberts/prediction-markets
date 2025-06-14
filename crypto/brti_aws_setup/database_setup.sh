#!/bin/bash

echo "🚀 Starting PostgreSQL setup..."

# Install PostgreSQL and contrib extensions
sudo apt update
sudo apt install -y postgresql postgresql-contrib

# Enable and start PostgreSQL
sudo systemctl enable postgresql
sudo systemctl start postgresql

# === Configure trust-based local access ===
PG_HBA="/etc/postgresql/16/main/pg_hba.conf"
POSTGRESQL_CONF="/etc/postgresql/16/main/postgresql.conf"

echo "🔧 Updating pg_hba.conf and postgresql.conf..."

# Allow trust auth for all local connections
sudo sed -i 's/^local\s\+all\s\+all\s\+.*/local   all             all                                     trust/' "$PG_HBA"
sudo sed -i 's/^host\s\+all\s\+all\s\+127\.0\.0\.1\/32\s\+.*/host    all             all             127.0.0.1\/32            trust/' "$PG_HBA"
sudo sed -i 's/^host\s\+all\s\+all\s\+::1\/128\s\+.*/host    all             all             ::1\/128                 trust/' "$PG_HBA"

# Restart PostgreSQL to apply changes
sudo systemctl restart postgresql

# === Create database, table, and grant permissions ===
echo "📦 Creating database and user..."
sudo -u postgres psql <<EOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_database WHERE datname = 'brti') THEN
        CREATE DATABASE brti;
        RAISE NOTICE '🆕 Database ''brti'' created.';
    END IF;
END
\$\$;

\c brti

-- Create table if not exists
CREATE TABLE IF NOT EXISTS brti_prices (
    id SERIAL PRIMARY KEY,
    price NUMERIC(10, 2),
    simple_average NUMERIC(10, 2),
    timestamp TIMESTAMPTZ
);

-- Grant full access to ubuntu user
GRANT ALL PRIVILEGES ON TABLE brti_prices TO ubuntu;
GRANT USAGE, SELECT ON SEQUENCE brti_prices_id_seq TO ubuntu;
EOF

echo "✅ PostgreSQL setup complete. Database: brti | User: ubuntu | Local access: trust (no password)"
