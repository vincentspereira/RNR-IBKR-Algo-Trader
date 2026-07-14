-- Provision the `keycloak` database used by the Keycloak service
-- (KC_DB_URL: jdbc:postgresql://postgres:5432/keycloak).
--
-- Docker runs every .sql in this directory as POSTGRES_USER (trading_user,
-- the cluster superuser) connected to the default `trading` database, so we
-- can create an additional database here. CREATE DATABASE defaults ownership
-- to the current user (trading_user), which matches Keycloak's
-- KC_DB_USERNAME=${POSTGRES_USER:-trading_user}, letting Keycloak create and
-- migrate its own schema. CREATE DATABASE cannot run inside a transaction.
CREATE DATABASE keycloak;
