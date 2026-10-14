-- One database, one schema per service (search_path set by each service).
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS ba;
CREATE SCHEMA IF NOT EXISTS designer;
CREATE SCHEMA IF NOT EXISTS wiki;
