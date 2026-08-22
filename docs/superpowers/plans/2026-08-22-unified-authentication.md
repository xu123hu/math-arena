# Unified Authentication System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a production-shaped login, registration, session, role-review, account-security, and administrator-review system for students, teachers, and researchers across the FastAPI backend and Vue frontend.

**Architecture:** Keep FastAPI/PostgreSQL as the identity source of truth and introduce a focused `app.domains.identity` package behind the existing `/api/auth` compatibility router. Access tokens remain short-lived bearer tokens in browser memory; rotating refresh tokens live in HttpOnly cookies and are serialized with PostgreSQL row locks. Vue uses one Pinia auth store, a refresh singleflight in the API client, role-aware guards, and dedicated authentication/onboarding/review pages.

**Tech Stack:** Python 3.11, FastAPI, Pydantic 2, SQLAlchemy 2 async, PostgreSQL, Alembic, Redis, Argon2id, pytest; Vue 3, Pinia, Vue Router, Vitest, Playwright, Vite.

**Spec:** `docs/superpowers/specs/2026-08-22-unified-authentication-design.md`

## Global Constraints

- Preserve unrelated dirty-worktree changes in `D:\math-arena` and `D:\frontend`; execute in isolated Git worktrees after user consent.
- Student self-registration is immediate; teacher and researcher bindings start `pending` unless a valid organization invite atomically approves them.
- Authorization always checks user status, session revocation, `security_version`, `active_role`, and approved role binding; JWT `roles[]` is never an authorization fact source.
- Access tokens expire after 15 minutes. Refresh cookies rotate on every use and replay revokes the entire token family.
- Passwords use Argon2id, accept 15–128 Unicode code points after NFC normalization, use a local blocklist, and do not impose composition or periodic-rotation rules.
- Production never falls back to the demo SMS provider. OTP purpose values are isolated and OTPs are single-use.
- Account lifecycle routes are the only routes available to `deletion_pending` identities.
- Existing API numeric `code` values remain compatible while new responses add stable `error_key` values.
- Every behavior change follows RED → verify expected failure → minimal GREEN → full relevant regression → narrow commit.
- Backend and frontend commits remain separate because they are separate Git repositories.

---

## File and Responsibility Map

### Backend (`D:\math-arena`)

- Create `services/api/app/domains/identity/types.py`: enums and typed current-identity value object.
- Create `services/api/app/domains/identity/security.py`: password, OTP, invite, refresh-token hashing helpers.
- Create `services/api/app/domains/identity/challenges.py`: challenge lifecycle, throttling, and provider orchestration.
- Create `services/api/app/domains/identity/sms.py`: `SmsProvider`, demo provider, Tencent adapter boundary, stable error mapping.
- Create `services/api/app/domains/identity/sessions.py`: access claims, refresh rotation, revocation, CSRF validation.
- Create `services/api/app/domains/identity/service.py`: login, registration, onboarding, role application, phone change, deletion.
- Create `services/api/app/domains/identity/router.py`: new `/api/auth` contract.
- Create `services/api/app/domains/identity/admin_router.py`: administrator identity-review contract.
- Create focused SQLAlchemy models under `services/api/app/models/identity.py` and export them from `app.models`.
- Modify `services/api/app/models/user.py` and `role_binding.py`: lifecycle and approval state.
- Modify `services/api/app/models/student_profile.py`: school stage, grade, and optional organization reference.
- Modify `services/api/app/gateway/auth.py`: database-backed current identity and role authorization.
- Modify `services/api/app/gateway/auth_router.py`: short compatibility delegates only.
- Modify `services/api/app/main.py`, `config.py`, dependency manifests, and deployment examples.
- Add Alembic revision `services/api/alembic/versions/auth_001_unified_identity.py`.
- Add focused tests under `services/api/tests/identity/` plus migration and compatibility tests.

### Frontend (`D:\frontend`)

- Create `src/api/auth.js`: typed-by-contract auth endpoint wrappers.
- Create `src/api/authSession.js`: in-memory token holder, CSRF bootstrap, refresh singleflight.
- Modify `src/api/client.js`: credentials, retry-once, stable errors, no token persistence.
- Rewrite `src/stores/auth.js`: bootstrap state machine, approved roles, role switching, logout/session actions.
- Replace `src/pages/Login.vue` and create `Register.vue`, `StudentOnboarding.vue`, `RoleApplication.vue`, `PendingReview.vue`, `AccountSecurity.vue`.
- Create `src/pages/admin/AdminIdentityReview.vue` and add it to admin navigation/router.
- Modify `src/router/index.js`, `src/main.js`, and Nginx configuration.
- Add Vitest tests under `test/auth/` and Playwright flow `e2e/auth.spec.ts`.

---

### Task 1: Identity schema and reversible migration

**Files:**
- Create: `services/api/app/models/identity.py`
- Create: `services/api/alembic/versions/auth_001_unified_identity.py`
- Modify: `services/api/app/models/user.py`
- Modify: `services/api/app/models/role_binding.py`
- Modify: `services/api/app/models/student_profile.py`
- Modify: `services/api/app/models/__init__.py`
- Test: `services/api/tests/identity/test_identity_models.py`
- Test: `services/api/tests/identity/test_identity_migration.py`

**Interfaces:**
- Produces `User.security_version: int`, `User.status: active|suspended|deletion_pending|deleted`.
- Produces `RoleBinding.status: pending|approved|rejected|suspended` and compatibility property `verified`.
- Produces models `UserCredential`, `AuthSession`, `AuthRefreshToken`, `RoleApplication`, `Organization`, `OrganizationInvite`, `IdentityAuditLog`, `UserConsent`, `AccountDeletionRequest`.
- Produces `StudentProfile.school_stage`, `StudentProfile.grade`, and optional `StudentProfile.organization_id` without allowing a self-declared class.

- [ ] **Step 1: Write failing model tests.** Assert table names, unique constraints, status defaults, `security_version == 1`, and that `RoleBinding(status="approved").verified is True` while pending is false.

```python
def test_role_binding_verified_is_derived():
    assert RoleBinding(role="teacher", status="approved").verified is True
    assert RoleBinding(role="teacher", status="pending").verified is False
```

- [ ] **Step 2: Run RED.** Run `services/api/.venv/Scripts/python.exe -m pytest services/api/tests/identity/test_identity_models.py -q` from `D:\math-arena`; expect import failure for `app.models.identity`.
- [ ] **Step 3: Add focused models and enum-backed validation.** Store database values as bounded strings to preserve Alembic portability; use UUID foreign keys and named unique/index constraints from the design spec.
- [ ] **Step 4: Run model tests GREEN.** Re-run the exact test command and expect all tests to pass.
- [ ] **Step 5: Write migration round-trip test.** Assert `upgrade head`, expected columns/tables/indexes, `downgrade m3_002_fullstack_closure`, and re-upgrade all succeed on the test database.
- [ ] **Step 6: Run migration RED.** Run `services/api/.venv/Scripts/python.exe -m pytest services/api/tests/identity/test_identity_migration.py -q`; expect missing revision/tables.
- [ ] **Step 7: Implement `auth_001_unified_identity`.** Backfill students and verified teachers as approved, unverified teachers as pending, researchers as pending except configured seed allowlist, and emit migration counts without deleting business data.
- [ ] **Step 8: Run migration and model regressions GREEN.** Run both new test files and `services/api/tests/test_models.py`.
- [ ] **Step 9: Commit backend schema slice.** Commit only model, migration, export, and the two test files as `feat(auth): add unified identity schema`.

### Task 2: Close the existing authorization vulnerability

**Files:**
- Create: `services/api/app/domains/identity/types.py`
- Modify: `services/api/app/gateway/jwt.py`
- Modify: `services/api/app/gateway/auth.py`
- Modify: `services/api/app/gateway/auth_router.py`
- Test: `services/api/tests/identity/test_authorization.py`
- Modify tests: `services/api/tests/test_auth.py`

**Interfaces:**
- Produces `CurrentIdentity(user_id: UUID, session_id: UUID, active_role: str, security_version: int)`.
- Produces `load_current_identity(credentials, db) -> CurrentIdentity`.
- Produces `require_role(*roles)` that reloads and verifies the approved active binding.
- Produces access claims `sub`, `sid`, `active_role`, `sv`, `iat`, `exp`; removes authorization dependence on `roles` and `verified`.

- [ ] **Step 1: Write RED tests for all five gates.** Create real user/session/binding rows and prove suspended user, revoked session, mismatched `security_version`, pending binding, and mismatched active role each return 401/403.

```python
@pytest.mark.parametrize("binding_status", ["pending", "rejected", "suspended"])
async def test_teacher_route_rejects_non_approved_binding(binding_status, identity_factory):
    token = await identity_factory(active_role="teacher", binding_status=binding_status)
    response = await client.get("/api/teacher/today", headers=bearer(token))
    assert response.status_code == 403
```

- [ ] **Step 2: Run RED.** Run `services/api/.venv/Scripts/python.exe -m pytest services/api/tests/identity/test_authorization.py -q`; confirm pending teacher/researcher access currently succeeds or dependency signature is missing.
- [ ] **Step 3: Implement database-backed identity resolution.** Decode only immutable claims, query user/session/current binding, compare `sv`, and return stable `AUTH_SESSION_REVOKED`, `AUTH_ACCOUNT_SUSPENDED`, or `AUTH_ROLE_NOT_APPROVED` details.
- [ ] **Step 4: Make role switch approval-only.** Query target binding with `status == "approved"`; access token contains the selected role only as `active_role`.
- [ ] **Step 5: Stop researcher auto-approval immediately.** Compatibility `/role/apply` creates `pending` for both teacher and researcher.
- [ ] **Step 6: Run GREEN and regressions.** Run the new authorization tests, `tests/test_auth.py`, teacher scope tests, and research router tests selected by `rg -l 'require_role' services/api/tests`.
- [ ] **Step 7: Commit authorization fix.** Commit as `fix(auth): enforce approved database roles`.

### Task 3: Purpose-bound SMS challenges and provider abstraction

**Files:**
- Create: `services/api/app/domains/identity/security.py`
- Create: `services/api/app/domains/identity/sms.py`
- Create: `services/api/app/domains/identity/challenges.py`
- Modify: `services/api/app/config.py`
- Modify: `services/api/app/gateway/redis.py`
- Modify: `services/api/requirements.txt`
- Modify: `services/api/pyproject.toml`
- Test: `services/api/tests/identity/test_sms_challenges.py`

**Interfaces:**
- `SmsPurpose = login|password_reset|phone_change_old|phone_change_new|admin_mfa|account_deletion`.
- `SmsProvider.send(phone: str, template: str, params: dict[str, str]) -> None`.
- `ChallengeService.create(phone, purpose, client_context) -> ChallengeIssued`.
- `ChallengeService.consume(challenge_id, phone, purpose, code) -> None` atomically marks success.

- [ ] **Step 1: Write RED tests.** Cover purpose mismatch, five failed attempts, one-time consume, expiry, phone/IP throttling, demo allowlist, production demo rejection, and Tencent error-category mapping.
- [ ] **Step 2: Run RED.** Run `services/api/.venv/Scripts/python.exe -m pytest services/api/tests/identity/test_sms_challenges.py -q`; expect missing domain modules.
- [ ] **Step 3: Implement challenge keys and Lua/transactional consume.** Store only `HMAC(challenge_id + phone + purpose + code)` plus metadata and TTL; never log phone/code together.
- [ ] **Step 4: Implement providers.** Demo uses injected code only outside production and only for allowlisted numbers; Tencent adapter has no SDK import at domain boundary and maps provider categories to stable keys.
- [ ] **Step 5: Add `/api/auth/challenges/sms`.** Always return a non-enumerating envelope and `retry_after`; production provider absence returns `SMS_PROVIDER_UNAVAILABLE`.
- [ ] **Step 6: Run GREEN and existing Redis/auth tests.** Run new tests plus the Redis section in `tests/test_auth.py`.
- [ ] **Step 7: Commit challenge slice.** Commit as `feat(auth): add secure sms challenges`.

### Task 4: Password policy and credential recovery

**Files:**
- Modify: `services/api/app/domains/identity/security.py`
- Modify: `services/api/app/domains/identity/service.py`
- Modify: `services/api/app/domains/identity/router.py`
- Create: `services/api/app/domains/identity/password_blocklist.txt`
- Test: `services/api/tests/identity/test_passwords.py`

**Interfaces:**
- `PasswordHasher.hash(password: str) -> str` using Argon2id.
- `PasswordHasher.verify_and_rehash(password, encoded) -> PasswordCheck(valid, replacement_hash)`.
- Endpoints `/api/auth/password/set`, `/api/auth/login/password`, `/api/auth/password/reset`.

- [ ] **Step 1: Write RED tests.** Assert NFC normalization, 14-character rejection, 15-character acceptance, 128 acceptance, 129 rejection, Unicode/space support, blocklist rejection, Argon2id hash prefix, and reset session revocation.
- [ ] **Step 2: Run RED.** Run `services/api/.venv/Scripts/python.exe -m pytest services/api/tests/identity/test_passwords.py -q`.
- [ ] **Step 3: Add `argon2-cffi` and implement minimal policy.** Perform length and blocklist checks before hashing; use constant-time verification and transparent parameter rehash.
- [ ] **Step 4: Implement set/login/reset services.** Reset consumes `password_reset` challenge, increments `security_version`, and revokes all sessions in one transaction.
- [ ] **Step 5: Run GREEN and dependency audit.** Run password tests and `pip check` in the backend virtual environment.
- [ ] **Step 6: Commit password slice.** Commit as `feat(auth): add argon2 password login and reset`.

### Task 5: Rotating refresh sessions, CSRF, and device revocation

**Files:**
- Create: `services/api/app/domains/identity/sessions.py`
- Modify: `services/api/app/domains/identity/router.py`
- Modify: `services/api/app/config.py`
- Test: `services/api/tests/identity/test_sessions.py`

**Interfaces:**
- `SessionService.issue(user, active_role, remember, device) -> IssuedSession(access_token, refresh_token, csrf_token)`.
- `SessionService.rotate(refresh_token, csrf_token) -> IssuedSession` using `SELECT ... FOR UPDATE` on refresh token and session rows.
- `SessionService.revoke(session_id, actor_id)` and `revoke_all(user_id)`.
- Cookies: `ma_refresh` HttpOnly/Secure/SameSite=Lax/path `/api/auth`; `ma_csrf` readable and matched to `X-CSRF-Token`.

- [ ] **Step 1: Write RED tests.** Cover 15-minute access expiry, 7/30-day absolute and idle limits, cookie flags, CSRF mismatch, logout, logout-all, device revoke, rotation, and reused-token family revocation.
- [ ] **Step 2: Add a real PostgreSQL concurrency test.** Submit the same refresh token twice with `asyncio.gather`; assert exactly one 200 and one replay failure, and the family is revoked.
- [ ] **Step 3: Run RED.** Run `services/api/.venv/Scripts/python.exe -m pytest services/api/tests/identity/test_sessions.py -q`.
- [ ] **Step 4: Implement token generation and HMAC lookup.** Persist active/used/revoked token history, update `last_seen_at`, and use configured trusted-proxy IP extraction before `/24` or `/64` truncation.
- [ ] **Step 5: Implement refresh/logout/session endpoints.** Add `Cache-Control: no-store` to authentication responses and clear cookies on terminal failures.
- [ ] **Step 6: Run GREEN and repeat concurrency test.** Run the test file three times to expose nondeterministic races, then run authorization tests.
- [ ] **Step 7: Commit session slice.** Commit as `feat(auth): add rotating refresh sessions`.

### Task 6: SMS login, student onboarding, and compatibility window

**Files:**
- Create/modify: `services/api/app/domains/identity/service.py`
- Create/modify: `services/api/app/domains/identity/router.py`
- Modify: `services/api/app/gateway/auth_router.py`
- Modify: `services/api/app/main.py`
- Test: `services/api/tests/identity/test_login_onboarding.py`
- Test: `services/api/tests/identity/test_auth_compatibility.py`

**Interfaces:**
- `/api/auth/login/sms` returns `{access_token, expires_in, user, onboarding_required}` and refresh/CSRF cookies.
- `/api/identity/onboarding/student` accepts nickname/name, stage, grade, optional school, and consent version.
- Legacy `/sms-code` and `/login` delegate for 14 天或两个稳定版本（以先到者为准） and emit deprecation metrics; `/login-by-code` cannot create accounts.

- [ ] **Step 1: Write RED login tests.** Cover existing login, atomic new-student creation under two concurrent requests, generic responses for unknown numbers, onboarding required, and active approved student role.
- [ ] **Step 2: Write RED compatibility tests.** Assert legacy endpoints delegate, emit `Deprecation`/`Sunset` headers, and class-code login returns `AUTH_CLASS_CODE_LOGIN_DEPRECATED` without user creation.
- [ ] **Step 3: Run RED.** Run both new files.
- [ ] **Step 4: Implement transaction-safe login and onboarding.** Use unique phone constraint recovery for concurrent registration and record consent version/time.
- [ ] **Step 5: Wire routers in `main.py`.** Keep exactly one effective handler per route and expose new OpenAPI schemas.
- [ ] **Step 6: Run GREEN and existing auth/classroom tests.** Verify no class membership flow regresses.
- [ ] **Step 7: Commit login slice.** Commit as `feat(auth): add sms login and student onboarding`.

### Task 7: Teacher/researcher applications, invitations, and administrator review

**Files:**
- Modify: `services/api/app/domains/identity/service.py`
- Create: `services/api/app/domains/identity/admin_router.py`
- Modify: `services/api/app/gateway/admin_router.py`
- Modify: `services/api/app/main.py`
- Test: `services/api/tests/identity/test_role_applications.py`
- Test: `services/api/tests/identity/test_identity_admin.py`

**Interfaces:**
- `/api/identity/role-applications` accepts the role-specific fields defined in the spec and optional proof metadata.
- Administrator list/detail/approve/reject/request-more-info/suspend/restore endpoints return stable status transitions.
- Invite creation returns plaintext once; redemption compares HMAC digest and atomically consumes quota.

- [ ] **Step 1: Write RED state-machine tests.** Prove student application paths, teacher/researcher pending status, resubmission rules, self-review denial, idempotent review, and audit rows.
- [ ] **Step 2: Write RED invitation race test.** Redeem a one-use invite twice concurrently and assert one approval and one exhausted response.
- [ ] **Step 3: Run RED.** Run both identity application/admin test files.
- [ ] **Step 4: Implement application and admin services.** Use transition guards, recent admin re-auth claim, separate reviewer identity, proof deletion schedule, and append-only audit writes in the same transaction.
- [ ] **Step 5: Implement high-entropy invitation flow.** Generate 128-bit values, show once, HMAC with `AUTH_INVITE_PEPPER`, lock the invitation row, and enforce account/IP/digest throttles.
- [ ] **Step 6: Run GREEN and `tests/test_admin.py`.** Confirm existing model configuration admin endpoints still authorize correctly.
- [ ] **Step 7: Commit review slice.** Commit as `feat(identity): add role application review`.

### Task 8: Phone change, account deletion, audit retention, and break-glass

**Files:**
- Modify: `services/api/app/domains/identity/service.py`
- Modify: `services/api/app/domains/identity/router.py`
- Create: `services/api/app/domains/identity/retention.py`
- Create: `services/api/scripts/identity_break_glass.py`
- Test: `services/api/tests/identity/test_account_lifecycle.py`
- Test: `services/api/tests/identity/test_break_glass.py`

**Interfaces:**
- Old/new phone challenges bind to one 15-minute change transaction.
- Deletion request has requested/cancelled/executed states and 7-day cooling period.
- Retention job archives security logs to at least 180 days and handles two-year admin audit/proof schedules.
- Break-glass CLI reads secret from stdin, creates a 15-minute one-time recovery token, and never exposes an HTTP route.

- [ ] **Step 1: Write RED lifecycle tests.** Cover old/new challenge mismatch, already-bound number, successful change revocation, deletion re-auth, restricted session, cancel, execution anonymization, and fresh re-registration isolation.
- [ ] **Step 2: Write RED retention and CLI tests.** Use frozen times and subprocess invocation; assert default-disabled behavior, no secret in argv/output, two-person metadata, and append-only audit.
- [ ] **Step 3: Run RED.** Run both new files.
- [ ] **Step 4: Implement lifecycle transactions and retention classifications.** Preserve only data with configured legal basis/end date and deny all non-lifecycle routes while pending deletion.
- [ ] **Step 5: Implement CLI without public route.** Require `AUTH_BREAK_GLASS_ENABLED=true`, stdin secret verification, trusted environment marker, work-order and two-operator identifiers.
- [ ] **Step 6: Run GREEN plus authorization/session regressions.** Verify phone change and deletion both revoke prior sessions.
- [ ] **Step 7: Commit lifecycle slice.** Commit as `feat(identity): add account lifecycle controls`.

### Task 9: Frontend in-memory session client and Pinia bootstrap

**Files:**
- Create: `D:\frontend\src\api\authSession.js`
- Create: `D:\frontend\src\api\auth.js`
- Modify: `D:\frontend\src\api\client.js`
- Modify: `D:\frontend\src\api\index.js`
- Rewrite: `D:\frontend\src\stores\auth.js`
- Test: `D:\frontend\test\auth\client.test.ts`
- Test: `D:\frontend\test\auth\store.test.ts`

**Interfaces:**
- Module-only `getAccessToken/setAccessToken`; no access token in local/session storage.
- One shared `refreshPromise: Promise<void> | null`; at most one refresh for concurrent 401 responses and one replay per original request.
- Store statuses `idle|bootstrapping|anonymous|authenticated|onboarding|pending_review|deletion_pending`.

- [ ] **Step 1: Write RED client tests.** Assert `credentials: "include"`, CSRF header on cookie mutations, three simultaneous 401s cause one refresh, replay once, refresh failure clears memory and redirects once, and localStorage never receives a token.
- [ ] **Step 2: Run RED.** Run `npm test -- test/auth/client.test.ts` from `D:\frontend`.
- [ ] **Step 3: Implement memory holder and request singleflight.** Separate raw refresh fetch from normal interceptor to prevent recursion.
- [ ] **Step 4: Run client GREEN.** Re-run the targeted test and existing teacher client tests.
- [ ] **Step 5: Write RED store tests.** Cover cold bootstrap from refresh cookie, anonymous bootstrap, approved-role filtering, role switch, pending review, logout-all, and deletion-pending state.
- [ ] **Step 6: Implement the Pinia state machine and run GREEN.** Cache only non-sensitive presentation preferences; obtain authoritative identity from `/auth/me`.
- [ ] **Step 7: Commit frontend session slice.** Commit in the frontend worktree as `feat(auth): add in-memory session bootstrap`.

### Task 10: Frontend login, registration, onboarding, and role application UX

**Files:**
- Rewrite: `D:\frontend\src\pages\Login.vue`
- Create: `D:\frontend\src\pages\Register.vue`
- Create: `D:\frontend\src\pages\StudentOnboarding.vue`
- Create: `D:\frontend\src\pages\RoleApplication.vue`
- Create: `D:\frontend\src\pages\PendingReview.vue`
- Create: `D:\frontend\src\components\auth\PhoneField.vue`
- Create: `D:\frontend\src\components\auth\OtpField.vue`
- Create: `D:\frontend\src\components\auth\PasswordField.vue`
- Test: `D:\frontend\test\auth\pages.test.ts`

**Interfaces:**
- One entry page with SMS/password tabs and explicit register link; no high-privilege role selector before authentication.
- Registration creates student identity first; teacher/researcher roles are applied after authentication.
- OTP send button reflects server `retry_after`; errors map from stable `error_key` to actionable Chinese copy.

- [ ] **Step 1: Write RED component tests.** Assert phone normalization/validation, countdown, SMS/password tab semantics, accessible labels, disabled double submit, new-user onboarding redirect, role application fields, and pending status display.
- [ ] **Step 2: Run RED.** Run `npm test -- test/auth/pages.test.ts`.
- [ ] **Step 3: Implement reusable fields and pages.** Preserve the established visual tokens but label the product platform-wide instead of “学生端 v4”; demo code text only appears when backend declares demo mode.
- [ ] **Step 4: Run GREEN and production build.** Run the page tests, full Vitest suite, and `npm run build`.
- [ ] **Step 5: Commit frontend UX slice.** Commit as `feat(auth): add role-aware login and onboarding`.

### Task 11: Router guards, account security, administrator review UI, and CSP

**Files:**
- Modify: `D:\frontend\src\router\index.js`
- Modify: `D:\frontend\src\main.js`
- Create: `D:\frontend\src\pages\AccountSecurity.vue`
- Create: `D:\frontend\src\pages\admin\AdminIdentityReview.vue`
- Modify: `D:\frontend\src\components\admin\AdminNav.vue`
- Modify: `D:\frontend\nginx.conf`
- Test: `D:\frontend\test\auth\router.test.ts`
- Test: `D:\frontend\test\auth\securityPages.test.ts`

**Interfaces:**
- Guards wait for auth bootstrap, require approved active role, preserve intended redirect, and route pending/deletion identities to their allowed pages.
- Security page lists/revokes sessions, changes phone, resets password, logs out all, and requests/cancels deletion.
- Admin page filters and reviews identity applications and requires re-auth before mutations.

- [ ] **Step 1: Write RED guard tests.** Cover cold refresh bootstrap, teacher pending denial, researcher suspended denial, admin active-role requirement, deep-link redirect, and deletion-pending restriction.
- [ ] **Step 2: Write RED page tests.** Cover device revoke, phone-change two-challenge state, deletion confirmation/cooling cancellation, application filters, review transitions, and re-auth prompt.
- [ ] **Step 3: Run RED.** Run both targeted frontend test files.
- [ ] **Step 4: Implement guards and pages.** Remove `getToken()`/`ma_token` route dependencies and route only from store state.
- [ ] **Step 5: Add security headers.** Start `Content-Security-Policy-Report-Only` with `default-src 'self'`, `script-src 'self'`, `object-src 'none'`, `base-uri 'self'`, `frame-ancestors 'none'`; retain only the currently necessary style allowance and document its removal metric, then promote the same policy to `Content-Security-Policy` after report validation.
- [ ] **Step 6: Run GREEN, full Vitest, typecheck, and build.** Also verify existing student/teacher/research routes remain registered.
- [ ] **Step 7: Commit frontend authorization slice.** Commit as `feat(identity): add account security and admin review`.

### Task 12: Cross-stack migration, security, and browser acceptance

**Files:**
- Create: `D:\frontend\e2e\auth.spec.ts`
- Modify: `D:\math-arena\.env.example`
- Modify: `D:\math-arena\deploy\docker-compose.yml`
- Create: `D:\math-arena\docs\audits\2026-08-22-unified-authentication-verification.md`

**Interfaces:**
- Test identities cover student, pending/approved/suspended teacher, pending/approved/suspended researcher, admin, and deletion-pending user.
- Verification report maps each design-spec section to automated evidence and records any externally blocked SMS/CAPTCHA integration honestly.

- [ ] **Step 1: Write E2E RED paths.** Student SMS registration/onboarding, teacher application/admin approval/relogin, researcher approval, rejected/suspended denial, role switch, password reset, session revoke, phone change, and deletion cancellation.
- [ ] **Step 2: Run E2E RED against the integrated stack.** Confirm failures occur at the first not-yet-wired boundary rather than from test setup.
- [ ] **Step 3: Add deployment configuration and startup validation.** Include all expiry/idle settings, SMS provider, demo allowlist, peppers, trusted proxies, admin phones, CAPTCHA adapter, and break-glass defaults without committing secrets.
- [ ] **Step 4: Apply Alembic upgrade to a copied/local test database.** Record pre/post counts and verify researcher downgrade, approved seed allowlist, and no loss of learning/class data.
- [ ] **Step 5: Run full fresh verification.** Backend: focused identity suite, all affected authorization/admin/class/teacher/research tests, Ruff on changed files, Alembic upgrade/downgrade/upgrade. Frontend: full Vitest, typecheck, production build, and Playwright auth flow.
- [ ] **Step 6: Perform security probes.** Verify OTP replay/purpose mismatch, refresh concurrency/replay, CSRF denial, pending-role denial, deleted/suspended session denial, invite race, phone enumeration resistance, CSP headers, and no browser storage access token.
- [ ] **Step 7: Write evidence report and final commits.** Include command outputs, counts, residual provider limitations, migration rollback command, and exact commit hashes; commit backend/deployment report and frontend E2E changes separately.

## Plan Self-Review

- Spec coverage: data model, five-gate authorization, SMS/provider tiers, password policy, refresh concurrency, onboarding, role review, invitations, phone change, deletion, audit retention, break-glass, frontend singleflight, CSP, compatibility deadline, and acceptance matrix each map to a numbered task.
- Type consistency: `status` values, `security_version`, `session_id`, active-role semantics, cookie names, and endpoint paths are consistent across backend and frontend tasks.
- Dependency ordering: schema precedes authorization; authorization precedes authentication issuance; sessions precede login; backend contracts precede frontend client/pages; acceptance runs last.
- Scope control: SSO, QR login, concrete production CAPTCHA vendor, and live Tencent credentials remain adapter/configuration work outside this delivery; production fails closed when required providers are unavailable.
- The plan contains no unspecified implementation step; each task names the behavior test, expected RED boundary, minimal implementation target, GREEN command, and commit boundary.
