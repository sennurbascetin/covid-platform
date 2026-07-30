-- ============================================================
-- Task 1: cost control.
-- Snowflake bills for compute time, so a single badly written query
-- can consume a trial's credits. This monitor caps monthly spend and
-- escalates: notify, then suspend after running queries finish, then
-- suspend immediately.
-- ============================================================
USE ROLE ACCOUNTADMIN;

CREATE RESOURCE MONITOR IF NOT EXISTS BOOTCAMP_RM
  WITH CREDIT_QUOTA = 5
  FREQUENCY = MONTHLY
  START_TIMESTAMP = IMMEDIATELY
  TRIGGERS
    ON 80 PERCENT DO NOTIFY
    ON 95 PERCENT DO SUSPEND
    ON 100 PERCENT DO SUSPEND_IMMEDIATE;

ALTER ACCOUNT SET RESOURCE_MONITOR = BOOTCAMP_RM;

SHOW RESOURCE MONITORS;

-- ------------------------------------------------------------
-- Key-pair authentication (see README step 1).
-- Snowflake no longer permits password auth for programmatic access.
-- Generate a key pair locally, then register the PUBLIC half here.
-- Replace both placeholders with your own values - this statement is
-- account-specific and will fail on any other user.
-- ------------------------------------------------------------
SELECT CURRENT_USER();   -- confirm the exact username to use below


-- ALTER USER <YOUR_USERNAME> SET RSA_PUBLIC_KEY='<PASTE_YOUR_PUBLIC_KEY>';
