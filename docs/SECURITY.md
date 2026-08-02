# Security Model

## Threat boundary

CodeSmell treats uploaded source as untrusted data. It parses source statically
and never imports or executes the uploaded project. ZIP extraction retains the
existing path traversal, symlink, member-count, size and compression-ratio
controls.

## Authentication

- Passwords use Argon2id and unique random salts.
- Access tokens use HS256 JWTs with issuer, audience, issued-at, not-before,
  expiry and token identifiers.
- The user record is reloaded for every request. Disabling an account therefore
  blocks subsequent requests even when an old token has not expired.
- Tokens are kept in browser local storage by the supplied frontend. Production
  deployments should keep access-token lifetimes short and apply browser hardening.
- Login rate limiting is configured in the supplied Nginx gateway.

## Authorization

- `admin`: user/model administration and all analyst/viewer operations.
- `analyst`: project and analysis mutations, report generation, read access.
- `viewer`: read-only access.

This release uses a shared research workspace. It does not claim tenant-level
isolation between organizations. Deploy separate instances when strict tenant
isolation is required.

## Model artifacts

The public API does not accept joblib/pickle model uploads. Administrators
register trusted M5 artifacts through the CLI. Registration and every later load
verify the model-card schema and SHA-256 digest.

## Reports

- HTML values are escaped.
- CSV strings beginning with spreadsheet formula characters are prefixed to
  prevent formula execution when opened in spreadsheet software.
- File names are generated from UUID-controlled directories and sanitized slugs.
- Stored SHA-256 values are verified before download.
- Project deletion removes generated report directories.

## HTTP hardening

The API and Nginx set request identifiers, anti-sniffing, frame denial,
referrer, permissions and content-security headers. Production configuration
requires explicit trusted hosts, HTTPS at the gateway, non-wildcard CORS and a
non-default JWT secret.

## Secrets

Never commit `.env`, JWT secrets, database passwords or bootstrap credentials.
Use a deployment secret manager. Remove bootstrap credentials after initial
administrator creation.

## Audit trail

Successful mutating API calls generate audit events with actor, request ID,
resource path and status. Privileged report generation and deletion also create
semantic audit events. Audit records do not contain passwords, tokens or raw
source code.

## Residual risks

- Static analysis can still consume significant CPU or memory on adversarially
  complex source; apply container limits and queue quotas in public deployments.
- JWT signing-secret rotation invalidates all existing tokens and should be
  planned operationally.
- The shared workspace is unsuitable for mutually untrusted tenants.
- Local storage tokens are exposed to successful same-origin script injection;
  maintain the supplied CSP and avoid unreviewed frontend dependencies.
