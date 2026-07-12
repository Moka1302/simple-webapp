-- This script runs automatically the FIRST time the db container starts
-- (Postgres only executes files in /docker-entrypoint-initdb.d on an empty data volume)

CREATE TABLE IF NOT EXISTS items (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO items (name, description) VALUES
    ('Front-End', 'Static page served by Nginx'),
    ('Back-End', 'Flask API service'),
    ('Database', 'PostgreSQL, isolated on the backend network'),
    ('Proxy', 'Nginx reverse proxy routing / and /api'),
    ('Monitoring', 'Prometheus + Grafana');
