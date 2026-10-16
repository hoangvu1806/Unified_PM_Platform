-- Separate database for the test containers, so tests never touch platform data.
CREATE DATABASE platform_test;
\connect platform_test
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS ba;
CREATE SCHEMA IF NOT EXISTS designer;
CREATE SCHEMA IF NOT EXISTS wiki;
