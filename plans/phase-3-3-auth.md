# Phase 3.3 — Auth + per-organization roles

**Branch:** `phase-3/django-backend` · **Code:** `apps/api/uadas_api/accounts/`, `settings/` · **Prior:** [phase-3-2-data-model.md](phase-3-2-data-model.md)
django-allauth was checked against its live docs and the installed source (65.19.7), not memory.

## Decisions

| Area | Decision |
|---|---|
| Sign-in | allauth **headless, browser client only** at `/api/auth/browser/v1/`; session cookie (`HttpOnly`, `SameSite=Lax`, `Secure` in prod), no tokens (`HEADLESS_CLIENTS=("browser",)`, `/api/auth/app/` is 404) |
| Login name | Email only (`ACCOUNT_LOGIN_METHODS={"email"}`, no username). `ModelBackend` first (NFKC + `LOWER(email)` lookup, same rule as the DB constraint), then allauth's |
| Verification | `mandatory` in prod (hard-wired, not an env switch), `optional` dev, `none` test. Link verification does **not** log in (allauth default kept: a leaked link is not a login) |
| Rate limits | login, failed login (per IP **and** per account), signup, password reset; counted in the default cache. Prod **requires** `REDIS_URL`; dev/test use locmem. `DJANGO_TRUSTED_PROXY_COUNT` for the client IP |
| Enumeration | `ACCOUNT_PREVENT_ENUMERATION` left at its default (on); a test fails if it is set to `False` |
| OAuth | GitHub and Google via `SOCIALACCOUNT_PROVIDERS`, present **only** when both `*_CLIENT_ID` and `*_CLIENT_SECRET` exist; one alone fails start-up. No tokens stored; provider email never auto-links to a local account |
| CSRF | Ninja exempts every view from the CSRF middleware and relies on the auth class, so `NinjaAPI(auth=SessionAuth(csrf=True))` is the **default** and only `/health` opts out; a guard test walks every operation. Bootstrap = allauth's `GET /config` (sets the cookie) |
| Provisioning | `save_user` of both allauth adapters, inside one `transaction.atomic()`: user + personal org + `owner` membership + audit. (`user_signed_up` fires after commit and could leave a user with no org.) Covers OAuth first login |
| Org selection | Path-based, stateless; `require_membership(request, org_id, min_role)` |
| Prod config | New required variables: `REDIS_URL`, `DEFAULT_FROM_EMAIL`, `EMAIL_HOST`, `FRONTEND_BASE_URL` (the last was not in the brief but the emailed links need it) |

## Endpoints

| Method and path | Minimum role | Notes |
|---|---|---|
| `GET /api/me` | any | user + memberships |
| `GET`, `POST /api/organizations` | any | list mine; create (caller = owner, audited); cap of 20 owned organizations → `409` |
| `GET /api/organizations/{org_id}/members` | viewer | |
| `PATCH .../members/{membership_id}` | admin | role only; cannot grant above own role; only members **strictly below** your role (an owner: anyone); stepping down yourself is allowed |
| `DELETE .../members/{membership_id}` | admin, or self | any member may leave; otherwise the same strictly-below rule |

Errors: `401` no session, `403` CSRF failure or role too low, `404` non-member (same body as a nonexistent organization), `409` last owner / cap, `422` bad body.

## Role matrix (`accounts/permissions.py`, order `viewer < editor < admin < owner`)

| Capability | viewer | editor | admin | owner |
|---|---|---|---|---|
| `read` | yes | yes | yes | yes |
| `write_data` | - | yes | yes | yes |
| `manage_members` | - | - | yes | yes |
| `delete_organization`, `transfer_ownership` | - | - | - | yes (endpoints not built) |

## Last-owner protection (deferred from 3.2)

An organization always keeps ≥ 1 owner. Enforced on `Membership.save()` (role change), `.delete()`, queryset `update()` / `delete()` / `bulk_update()` (so related managers too; an `F()`/`Value()` role is refused as unverifiable), and on **deleting a user** (the delete collector bypasses all of those). It reads the *stored* role and runs under a row lock on the organization (a Postgres-only test of two simultaneous demotions fails without it). Deleting an *organization* still cascades its owners. The `AuditEvent.actor` detach path is untouched.

## Audit

`user.signed_up`, `organization.created` (`{"personal": bool}`), `membership.role_changed` (`from`, `to`, `user_id`), `membership.removed` (`role`, `user_id`, `self`), `user.logged_in`, `user.logged_out` (Django signals, so every login path is covered). Ids and role names only. Rows are tenant-owned, so login/logout are filed under the user's **oldest** membership; a user with none records nothing.

## Threat notes and limits

- **Brute force / stuffing:** per-IP and per-account limits; they only hold across workers with Redis, and only with the right proxy count. The per-account key is the NFKC-normalised, lower-cased address with no `Host` component (allauth's default let a Unicode twin spelling or a different `Host` header start a fresh budget). A locked-out login is a `400` with code `too_many_login_attempts` (allauth), per-IP limits are `429`.
- **Session fixation / CSRF:** login rotates session and CSRF token; unsafe methods need the header; `SameSite=Lax`; CORS credentials only for listed origins.
- **Enumeration:** protected for signup (mandatory mode) and reset. With `optional`/`none` verification (dev/test) allauth reveals "email taken".
- **Org probing:** non-members get 404; the 404 body is identical for existing and missing organizations.
- **Password rules:** four validators, min length 12. `UserAttributeSimilarityValidator` **cannot fire at signup** (allauth validates before a user exists); it does on change/reset.
- **A sole owner cannot be deleted** (their organization would be ownerless), which today includes everyone with a personal organization. Needs the offboarding step below.
- **Emails:** both adapters normalise (NFKC) the address before allauth decides "taken?" (signup form and OAuth), and `clean_email` gives an existing user with no `EmailAddress` row (made by `create_user`/`createsuperuser`; allauth cannot see them) an unverified one, so duplicate signups answer like any other (`400 email_taken`; in prod `401` "check your mail") instead of a 500.
- **Stale rows:** the member services lock the organization and re-read both roles inside their transaction (an admin demoted a moment ago cannot act; a target just promoted to owner is protected) and refuse cross-organization pairs. A membership that vanished meanwhile (actor or target) is `404`, not `403`.
- **Test hermeticity:** `uadas_api.pytest_env` (a `-p` plugin in `addopts`) removes `GITHUB_*`/`GOOGLE_*` from the environment before pytest-django loads settings; a conftest would run too late.
- **Signup atomicity is partial:** user + organization + membership + audit are one transaction, but allauth creates the `EmailAddress` row *after* `save_user` returns, outside it; a failure in that last step would leave a user without one.
- **Soft limits:** the 20-organization cap is counted under a row lock on the creating user (Postgres race test), but it limits *creation* only: leaving an organization and being promoted owner of another still evades it (accepted); the Ninja routes have no per-user throttle yet (only allauth's auth limits); any member (viewer included) can see other members' emails and the personal organization's name/slug derive from the email local part.
- **Policy:** admins manage only members strictly below them; peer admins and owners are changed or removed only by an owner (so one admin cannot strip the others).
- **Python-level only:** `_raw_delete`, raw SQL, `User._base_manager` and the Organization cascade bypass the guards (same stance as 3.2).
- `EMAIL_BACKEND` is the pre-Django-7 spelling (a `RemovedInDjango70Warning` shows in tests); `MAILERS` needs 6.1, the project allows 6.0. Migrate before 7.

## Deferred (not built)

Organization offboarding / hard purge and user erasure · email invitations (members can be re-roled and removed, not added) · API keys · MFA (`allauth.mfa`) · ownership-transfer and delete-organization endpoints (tiers fixed, routes absent) · login-by-code / passkeys · audit-log read endpoint · email-change flow review · fan-out of login events to every organization.
