# Security Policy

## Supported Versions

We support security updates for the current main branch and active releases of Agri-Vision.

| Version | Supported          |
| ------- | ------------------ |
| Main    | :white_check_mark: |
| >= 1.0  | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability within this project, please do not disclose it publicly. Instead, report it through one of the following methods:

1. **GitHub Security Advisories**: Submit a draft advisory via the **Security** tab of the repository.
2. **Contact Maintainers**: Reach out directly to the repository maintainers or file a private issue if supported.

We will acknowledge your report within 48 hours and work with you to resolve the vulnerability in a timely manner.

## Account Lockout Protection

Password logins are protected by persistent account lockout metadata on the user record. Failed password attempts increment a counter, record the failed timestamp/IP, and temporarily lock the account when the configured threshold is reached. Successful login resets the counter, clears lockout state, and records successful login metadata.

Default policy:

- `ACCOUNT_LOCKOUT_ENABLED=true`
- `MAX_FAILED_LOGIN_ATTEMPTS=5`
- `LOCKOUT_DURATION_MINUTES=15`
- `ENABLE_SECURITY_AUDIT=true`

Expired lockouts are cleared on the next login attempt, so no cron job is required. Security events are emitted through the existing audit logger using actions such as `AUTH_FAILED`, `ACCOUNT_LOCKED`, `ACCOUNT_UNLOCKED`, and `AUTH_SUCCESS`.
