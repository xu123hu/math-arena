# Role-Selective SMS Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let students, teachers, and researchers select their SMS registration and login identity while preserving administrator approval for professional workspaces and eliminating cross-workspace redirects.

**Architecture:** The identity service owns registration, role selection, and pending-role state. A professional role must be approved before a teacher or researcher session is issued; a pending selection receives only an approved base session marked with `pending_role`, so the client can show review status without granting professional authority. The Vue client submits an explicit target role and routes from the server-returned state; Tencent SMS is a concrete provider adapter selected solely by environment configuration.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async/Alembic, Redis, Tencent Cloud SMS Python SDK 3.0, Vue 3, Pinia, Vue Router, Vitest, Playwright, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-role-selective-sms-authentication-design.md`

## Global Constraints

- Public selectable roles are exactly `student`, `teacher`, and `researcher`; public requests cannot request `admin`.
- A teacher or researcher token is issued only when its `RoleBinding.status` is `approved`.
- Registration challenges use purpose `registration`; they cannot be consumed as login challenges.
- A pending professional selection must never be silently redirected to `/overview`.
- `AUTH_SMS_PROVIDER` accepts only `demo` and `tencent`; production rejects `demo` and incomplete Tencent configuration.
- Demo code is returned only by the demo provider and only outside production for configured allowlisted phones.
- Do not add credentials, signatures, template IDs, or phone numbers to tracked files.
- Use the existing isolated worktrees: `D:\worktrees\math-arena-auth` and `D:\worktrees\frontend-auth`.

---

## File structure

| Path | Responsibility |
| --- | --- |
| `services/api/app/models/identity.py` | Persist the pending professional role attached to a base session. |
| `services/api/alembic/versions/auth_002_role_selective_sms.py` | Upgrade/downgrade the production schema for the pending role marker. |
| `services/api/app/domains/identity/service.py` | Create identities, submit professional registrations, and resolve target-role state. |
| `services/api/app/domains/identity/router.py` | Validate public registration/login payloads and issue correct sessions. |
| `services/api/app/gateway/auth_router.py` | Expose pending identity state in `/me`, clear it on approved role switch, and retire unsafe legacy teacher registration. |
| `services/api/app/domains/identity/sms.py` | Own Tencent SDK 3.0 request construction and stable provider errors. |
| `services/api/app/config.py` and `.env.example` | Validate and document SMS provider configuration. |
| `services/api/tests/identity/test_login_onboarding.py` | API-level registration and SMS role-selection contracts. |
| `services/api/tests/identity/test_passwords.py` | Password role-selection contract. |
| `services/api/tests/identity/test_sms_challenges.py` | Registration purpose and Tencent provider contracts. |
| `services/api/tests/identity/test_auth_config.py` | Tencent production validation. |
| `services/api/tests/identity/test_auth_compatibility.py` | Legacy teacher registration retirement. |
| `src/api/auth.js` and `src/stores/auth.js` | Frontend request methods and server-authored identity status. |
| `src/pages/Login.vue` and `src/pages/Register.vue` | Explicit workspace selection and role-specific registration fields. |
| `src/router/index.js` | Route according to approved active role or pending identity state. |
| `src/mock/server.js` and `src/config/mockIdentity.ts` | Contract-faithful opt-in mock identities. |
| `test/auth/*.test.ts`, `test/teacher/mockIdentity.test.ts`, `e2e/auth.spec.ts` | UI, store, route, mock, and browser acceptance tests. |

## Task 1: Persist an explicit pending professional login target

**Files:**
- Modify: `services/api/app/models/identity.py`
- Create: `services/api/alembic/versions/auth_002_role_selective_sms.py`
- Modify: `services/api/app/domains/identity/sessions.py`
- Modify: `services/api/app/gateway/auth_router.py`
- Test: `services/api/tests/identity/test_sessions.py`
- Test: `services/api/tests/identity/test_authorization.py`

**Interfaces:**
- Produces: `AuthSession.pending_role: str | None` and `SessionService.issue(db, user, active_role, *, remember, pending_role: str | None = None)`.
- Produces: `GET /api/auth/me` field `identity_status: "authenticated" | "pending_review" | "needs_more_info" | "rejected" | "not_available"` and optional `pending_role`.
- Consumes: existing `RoleBinding.status` and `RoleApplication` state.

- [ ] **Step 1: Write the failing session persistence test**

```python
async def test_session_preserves_pending_role_across_refresh(identity_db):
    user = await approved_student(identity_db)
    issued = await SessionService(refresh_pepper="test-pepper").issue(
        identity_db, user, "student", remember=False, pending_role="teacher"
    )
    await identity_db.flush()

    stored = await identity_db.get(AuthSession, issued.session_id)
    assert stored.active_role == "student"
    assert stored.pending_role == "teacher"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest -q tests/identity/test_sessions.py::test_session_preserves_pending_role_across_refresh`

Expected: FAIL because `SessionService.issue` has no `pending_role` parameter and the model has no column.

- [ ] **Step 3: Write the minimal persistence implementation and migration**

```python
# models/identity.py
pending_role: Mapped[str | None] = mapped_column(String(16), nullable=True)

# sessions.py
async def issue(self, db, user, active_role, *, remember, pending_role=None):
    auth_session = AuthSession(
        user_id=user.id,
        security_version=user.security_version,
        active_role=active_role,
        pending_role=pending_role,
        remember=remember,
        last_seen_at=now,
        idle_expires_at=idle_expires_at,
        expires_at=absolute_expires_at,
    )
```

Create an Alembic revision that adds nullable `pending_role VARCHAR(16)` to `auth_sessions` in `upgrade()` and drops the same column in `downgrade()`. Preserve all existing session rows with `NULL`.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `pytest -q tests/identity/test_sessions.py tests/identity/test_authorization.py`

Expected: PASS; authorization still checks only `active_role`, never `pending_role`.

- [ ] **Step 5: Add `/auth/me` and role-switch behavior tests**

```python
async def test_me_reports_pending_role_without_elevating_active_role(client, approved_student_with_pending_teacher):
    response = await client.get("/api/auth/me", headers=student_session_headers)
    assert response.json()["data"]["active_role"] == "student"
    assert response.json()["data"]["pending_role"] == "teacher"
    assert response.json()["data"]["identity_status"] == "pending_review"

async def test_switch_to_approved_role_clears_pending_role(client, approved_teacher_with_pending_session):
    response = await client.post("/api/auth/role/switch", json={"role": "teacher"}, headers=headers)
    assert response.status_code == 200
    assert (await current_session()).pending_role is None
```

- [ ] **Step 6: Run the new API tests, then commit**

Run: `pytest -q tests/identity/test_sessions.py tests/identity/test_authorization.py`

Run: `git add services/api/app/models/identity.py services/api/alembic/versions services/api/app/domains/identity/sessions.py services/api/app/gateway/auth_router.py services/api/tests/identity/test_sessions.py services/api/tests/identity/test_authorization.py && git commit -m "feat(auth): retain pending professional login intent"`

Expected: tests pass and one focused backend commit exists.

## Task 2: Add purpose-bound SMS registration for all public roles

**Files:**
- Modify: `services/api/app/domains/identity/challenges.py`
- Modify: `services/api/app/domains/identity/router.py`
- Modify: `services/api/app/domains/identity/service.py`
- Test: `services/api/tests/identity/test_login_onboarding.py`
- Test: `services/api/tests/identity/test_sms_challenges.py`

**Interfaces:**
- Produces: `POST /api/auth/register/sms`.
- Consumes: `SmsRegistrationRequest` with `phone`, `challenge_id`, `code`, `role`, `consent_version`, and role-application fields.
- Produces: a student session plus `onboarding_required: true` for student; a base session plus `identity_status: "pending_review"`, `pending_role`, and application summary for teacher/researcher.

- [ ] **Step 1: Write the failing registration API tests**

```python
async def test_student_sms_registration_requires_registration_challenge():
    response = await client.post("/api/auth/register/sms", json={
        "phone": phone, "challenge_id": "registration", "code": "123456",
        "role": "student", "consent_version": "2026-08-24",
    })
    assert response.status_code == 200
    assert response.json()["data"]["user"]["active_role"] == "student"
    assert response.json()["data"]["onboarding_required"] is True

async def test_teacher_sms_registration_creates_pending_application_not_teacher_session():
    response = await client.post("/api/auth/register/sms", json={
        "phone": phone, "challenge_id": "registration", "code": "123456",
        "role": "teacher", "consent_version": "2026-08-24",
        "organization_name": "示例中学", "teaching_stage": "高中", "subject": "数学",
    })
    data = response.json()["data"]
    assert data["user"]["active_role"] == "student"
    assert data["pending_role"] == "teacher"
    assert data["identity_status"] == "pending_review"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest -q tests/identity/test_login_onboarding.py -k "registration"`

Expected: FAIL with `404` because `/api/auth/register/sms` does not exist.

- [ ] **Step 3: Implement the minimal registration contract**

```python
# challenges.py
ALLOWED_PURPOSES = {
    "login", "registration", "password_reset", "phone_change_old",
    "phone_change_new", "admin_mfa", "account_deletion",
}

# service.py
async def register_sms(self, db, *, phone: str, role: str, consent_version: str, **application_fields) -> tuple[User, bool, RoleApplication | None]:
    user, created = await self.login_sms(db, phone)
    if role == "student":
        return user, created, None
    user.onboarding_status = "completed"
    application = await self.submit_role_application(db, user.id, role=role, **application_fields)
    return user, created, application
```

Add a Pydantic request model that restricts `role` to `student|teacher|researcher`, validates `organization_name` for professional roles, validates `research_direction` for researcher, consumes purpose `registration`, and issues a base student session with `pending_role=role` only for a professional registration.

- [ ] **Step 4: Run registration and purpose-isolation tests**

Run: `pytest -q tests/identity/test_login_onboarding.py tests/identity/test_sms_challenges.py`

Expected: PASS; a `login` challenge consumed at `/register/sms` returns `AUTH_CHALLENGE_PURPOSE_MISMATCH`.

- [ ] **Step 5: Add duplicate and researcher coverage**

```python
async def test_researcher_registration_requires_research_direction():
    response = await client.post("/api/auth/register/sms", json={
        "phone": phone, "challenge_id": "registration", "code": "123456",
        "role": "researcher", "organization_name": "数研院", "consent_version": "2026-08-24",
    })
    assert response.status_code == 422

async def test_professional_registration_reuses_identity_without_duplicate_student_binding():
    await register_teacher(phone)
    assert await count_user_bindings(phone, "student") == 1
```

- [ ] **Step 6: Commit the complete registration slice**

Run: `git add services/api/app/domains/identity/challenges.py services/api/app/domains/identity/router.py services/api/app/domains/identity/service.py services/api/tests/identity/test_login_onboarding.py services/api/tests/identity/test_sms_challenges.py && git commit -m "feat(auth): add role-selective SMS registration"`

Expected: focused tests pass and exactly one backend commit is created.

## Task 3: Make SMS and password login honor the selected approved role

**Files:**
- Modify: `services/api/app/domains/identity/router.py`
- Modify: `services/api/app/domains/identity/service.py`
- Test: `services/api/tests/identity/test_login_onboarding.py`
- Test: `services/api/tests/identity/test_passwords.py`
- Test: `services/api/tests/identity/test_role_applications.py`

**Interfaces:**
- Produces: `IdentityService.resolve_login_role(db, user, preferred_role) -> LoginRoleResolution`.
- Consumes: optional `preferred_role` on `SmsLoginRequest` and `PasswordLoginRequest`.
- Produces: exact approved active role or a base session marked with the pending/rejected professional state.

- [ ] **Step 1: Write failing role-selection tests**

```python
async def test_approved_teacher_sms_login_issues_teacher_session():
    await create_user_with_bindings(phone, [("student", "approved"), ("teacher", "approved")])
    response = await sms_login(phone, preferred_role="teacher")
    assert response.json()["data"]["user"]["active_role"] == "teacher"

async def test_pending_teacher_selection_does_not_fall_back_to_student_home():
    await create_user_with_bindings(phone, [("student", "approved"), ("teacher", "pending")])
    response = await sms_login(phone, preferred_role="teacher")
    data = response.json()["data"]
    assert data["user"]["active_role"] == "student"
    assert data["identity_status"] == "pending_review"
    assert data["pending_role"] == "teacher"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest -q tests/identity/test_login_onboarding.py -k "teacher_sms_login or pending_teacher_selection"`

Expected: FAIL because SMS login always issues `student` and request validation rejects `preferred_role`.

- [ ] **Step 3: Implement a single role-resolution function**

```python
@dataclass(frozen=True)
class LoginRoleResolution:
    active_role: str
    pending_role: str | None
    identity_status: str

async def resolve_login_role(self, db, user, preferred_role: str | None) -> LoginRoleResolution:
    # approved preferred role -> that role
    # pending/needs_more_info/rejected preferred professional role -> approved base student + matching state
    # absent preferred professional role -> raise IdentityError(
    #     "AUTH_ROLE_NOT_AVAILABLE", "该手机号尚未申请此身份", 403
    # )
    # no preference -> last approved role, then student, then fixed role order
```

Use this function in both `/login/sms` and `/login/password`. Do not call `login_sms` in an existing-user login path to add bindings; only `/register/sms` may create the initial student binding. Issue the session using `resolution.active_role` and `resolution.pending_role` and return the same response fields in both login APIs.

- [ ] **Step 4: Run SMS, password, and approval transition tests**

Run: `pytest -q tests/identity/test_login_onboarding.py tests/identity/test_passwords.py tests/identity/test_role_applications.py`

Expected: PASS; approved teacher/researcher requests receive matching sessions, and approval revokes a pending-session user’s prior session.

- [ ] **Step 5: Commit the role-selection slice**

Run: `git add services/api/app/domains/identity/router.py services/api/app/domains/identity/service.py services/api/tests/identity/test_login_onboarding.py services/api/tests/identity/test_passwords.py services/api/tests/identity/test_role_applications.py && git commit -m "fix(auth): issue sessions for selected approved role"`

Expected: focused tests pass and the commit contains no unrelated gateway changes.

## Task 4: Wire Tencent Cloud SMS and retire unsafe legacy teacher registration

**Files:**
- Modify: `services/api/app/domains/identity/sms.py`
- Modify: `services/api/app/domains/identity/router.py`
- Modify: `services/api/app/config.py`
- Modify: `.env.example`
- Modify: `services/api/pyproject.toml`
- Modify: `services/api/requirements.txt`
- Modify: `services/api/app/gateway/auth_router.py`
- Test: `services/api/tests/identity/test_sms_challenges.py`
- Test: `services/api/tests/identity/test_auth_config.py`
- Test: `services/api/tests/identity/test_auth_compatibility.py`

**Interfaces:**
- Produces: `TencentSmsProvider.from_config(config)` with an async `send(phone, purpose, code)` boundary.
- Consumes: `TENCENT_SMS_SECRET_ID`, `TENCENT_SMS_SECRET_KEY`, `TENCENT_SMS_SDK_APP_ID`, `TENCENT_SMS_SIGN_NAME`, `TENCENT_SMS_TEMPLATE_ID`, `TENCENT_SMS_REGION`, and `TENCENT_SMS_TEMPLATE_PARAMS`.
- Produces: `410 AUTH_LEGACY_TEACHER_REGISTRATION_RETIRED` from `/api/auth/register/teacher`.

- [ ] **Step 1: Write failing Tencent request and validation tests**

```python
async def test_tencent_sender_uses_e164_and_template_parameters(fake_tencent_client):
    provider = TencentSmsProvider.from_config(valid_tencent_config, client_factory=fake_tencent_client)
    await provider.send("13800138000", "login", "123456")
    assert fake_tencent_client.request.PhoneNumberSet == ["+8613800138000"]
    assert fake_tencent_client.request.TemplateParamSet == ["123456", "5"]

def test_production_rejects_missing_tencent_sms_settings():
    with pytest.raises(RuntimeError, match="TENCENT_SMS_SECRET_ID"):
        Settings(
            app_env="production", auth_sms_provider="tencent",
            jwt_secret="a-production-secret-that-is-long-enough",
            auth_otp_pepper="a" * 32, auth_refresh_token_pepper="b" * 32,
            auth_invite_pepper="c" * 32,
        ).validate_production()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest -q tests/identity/test_sms_challenges.py tests/identity/test_auth_config.py`

Expected: FAIL because the current Tencent provider has no configured sender and production validation ignores Tencent credentials.

- [ ] **Step 3: Implement the concrete, dependency-injected Tencent adapter**

```python
async def _send_with_sdk(config: TencentSmsConfig, phone: str, code: str) -> str | None:
    # construct Tencent SDK 3.0 SendSmsRequest with SmsSdkAppId, SignName,
    # TemplateId, PhoneNumberSet=[f"+86{phone}"], TemplateParamSet=params
    # raise a code-bearing exception when SendStatusSet[0].Code != "Ok"

class TencentSmsProvider:
    @classmethod
    def from_config(
        cls, config: TencentSmsConfig, *, client_factory: Callable[[TencentSmsConfig], object] | None = None
    ) -> "TencentSmsProvider":
        return cls(sender=build_tencent_sender(config, client_factory=client_factory))
```

Use `asyncio.to_thread` for the synchronous SDK call. Add `tencentcloud-sdk-python` to both backend dependency manifests. Parse the JSON parameter list once in `Settings`; allow only strings with `{code}` replacement. Map SDK and recipient status codes with the existing stable error mapping. Change `get_challenge_service()` to construct demo only for `demo`, Tencent only for `tencent`, and reject any other configured provider.

- [ ] **Step 4: Add configuration documentation and retire legacy teacher registration**

```env
AUTH_SMS_PROVIDER=tencent
TENCENT_SMS_REGION=ap-guangzhou
TENCENT_SMS_TEMPLATE_PARAMS=["{code}","5"]
```

Replace the legacy `/register/teacher` handler body with `HTTPException(status_code=410, detail={"code": 41001, "error_key": "AUTH_LEGACY_TEACHER_REGISTRATION_RETIRED", "message": "请使用统一注册入口提交教师身份审核"})`. Its regression test must assert no user, binding, session, or token is created.

- [ ] **Step 5: Run all SMS/config/compatibility tests, then commit**

Run: `pytest -q tests/identity/test_sms_challenges.py tests/identity/test_auth_config.py tests/identity/test_auth_compatibility.py`

Run: `git add services/api/app/domains/identity/sms.py services/api/app/domains/identity/router.py services/api/app/config.py .env.example services/api/pyproject.toml services/api/requirements.txt services/api/app/gateway/auth_router.py services/api/tests/identity/test_sms_challenges.py services/api/tests/identity/test_auth_config.py services/api/tests/identity/test_auth_compatibility.py && git commit -m "feat(auth): configure Tencent SMS provider safely"`

Expected: all focused tests pass; no vendor credential appears in the diff.

## Task 5: Make frontend auth state and mocks preserve identity intent

**Files:**
- Modify: `src/api/auth.js`
- Modify: `src/stores/auth.js`
- Modify: `src/router/index.js`
- Modify: `src/config/mockIdentity.ts`
- Modify: `src/mock/server.js`
- Test: `test/auth/store.test.ts`
- Test: `test/auth/router.test.ts`
- Test: `test/teacher/mockIdentity.test.ts`

**Interfaces:**
- Produces: `authApi.registerSms(payload)`.
- Consumes: login/registration `identity_status`, `pending_role`, and `user.active_role` response values.
- Produces: `roleHome('teacher') === '/teacher/today'`, `roleHome('researcher') === '/research'`, and pending review navigation without role inference.

- [ ] **Step 1: Write failing client-state tests**

```typescript
it('keeps a server-reported pending teacher intent out of the student home', async () => {
  authMocks.loginSms.mockResolvedValue({
    access_token: 'student-base-token', identity_status: 'pending_review', pending_role: 'teacher',
    onboarding_required: false, user: studentWithPendingTeacher,
  })
  const store = useAuthStore()
  await store.loginSms({ phone: '13800138000', preferred_role: 'teacher' })
  expect(store.status).toBe('pending_review')
})

it('routes an approved researcher root to research', () => {
  expect(resolveAuthNavigation(route('/'), researcherAuth)).toEqual({ path: '/research' })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- --run test/auth/store.test.ts test/auth/router.test.ts test/teacher/mockIdentity.test.ts`

Expected: FAIL because login state ignores `identity_status` and mock identity lacks researcher/admin variants.

- [ ] **Step 3: Implement minimal contract-preserving state and mock changes**

```javascript
async loginSms(payload) {
  const data = await authApi.loginSms(payload)
  setAccessToken(data.access_token)
  this.applyIdentity({ ...data.user, identity_status: data.identity_status, pending_role: data.pending_role })
  return data
}
```

Update `deriveStatus` to honor valid server-provided identity state before ordinary onboarding checks. Add `registerSms` to the API object. Have mock `/auth/register/sms`, `/auth/login/sms`, `/auth/login/password`, `/auth/me`, and `/auth/role/switch` return role-specific values consistent with the real contract. Extend `resolveMockUser` and preview-token recognition to student, teacher, researcher, and admin.

- [ ] **Step 4: Run the focused frontend tests**

Run: `npm test -- --run test/auth/store.test.ts test/auth/router.test.ts test/teacher/mockIdentity.test.ts`

Expected: PASS; a teacher/researcher mock never resolves to a student root path.

- [ ] **Step 5: Commit the frontend state slice**

Run: `git add src/api/auth.js src/stores/auth.js src/router/index.js src/config/mockIdentity.ts src/mock/server.js test/auth/store.test.ts test/auth/router.test.ts test/teacher/mockIdentity.test.ts && git commit -m "fix(auth): preserve selected role in client state"`

Expected: focused tests pass and the frontend worktree has one focused commit.

## Task 6: Add role selection to login and registration UI

**Files:**
- Modify: `src/pages/Login.vue`
- Modify: `src/pages/Register.vue`
- Modify: `src/components/auth/OtpField.vue`
- Test: `test/auth/pages.test.ts`

**Interfaces:**
- Consumes: `auth.loginSms({ phone, challenge_id, code, remember, preferred_role })` and `auth.loginPassword({ phone, password, remember, preferred_role })`.
- Consumes: `authApi.registerSms({ phone, challenge_id, code, role, consent_version, organization_name, department, staff_or_student_id, teaching_stage, subject, research_direction })`.
- Produces: a direct `router.push(roleHome(data.user.active_role))` for approved login; `/identity/pending` for `pending_review` or `needs_more_info`; student onboarding only when `onboarding_required` is true.

- [ ] **Step 1: Write failing page tests**

```typescript
it('lets users select student, teacher, or researcher before SMS login', () => {
  const wrapper = mount(Login, {
    global: { plugins: [createPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
  expect(wrapper.get('select[name="preferred_role"]').text()).toContain('教师端')
  expect(wrapper.get('select[name="preferred_role"]').text()).toContain('科研端')
})

it('shows teacher fields and posts a registration-purpose verification request', async () => {
  const wrapper = mount(Register, {
    global: { plugins: [createPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
  await wrapper.get('select[name="role"]').setValue('teacher')
  expect(wrapper.get('input[name="organization_name"]').exists()).toBe(true)
  expect(wrapper.findComponent(OtpField).props('purpose')).toBe('registration')
})
```

- [ ] **Step 2: Run the page tests to verify they fail**

Run: `npm test -- --run test/auth/pages.test.ts`

Expected: FAIL because Login has no public role selector and Register labels itself as student-only with purpose `login`.

- [ ] **Step 3: Implement explicit selection and response-directed navigation**

```javascript
const preferredRole = ref('student')
const destination = data.identity_status === 'pending_review' || data.identity_status === 'needs_more_info'
  ? '/identity/pending'
  : data.onboarding_required
    ? '/onboarding/student'
    : roleHome(data.user.active_role)
```

Import `roleHome` from the router. Keep `route.query.redirect` only when it requires the returned active role; otherwise use `roleHome` to prevent a stale student deep link from receiving a teacher session or vice versa. Add teacher fields (`organization_name`, `teaching_stage`, `subject`, optional department and staff ID) and researcher fields (`organization_name`, required `research_direction`, optional department) to Register. Surface API errors with existing accessible alert markup.

- [ ] **Step 4: Run page tests and type checking**

Run: `npm test -- --run test/auth/pages.test.ts`

Run: `npm run typecheck`

Expected: PASS with no Vue template/type diagnostics.

- [ ] **Step 5: Commit the UI slice**

Run: `git add src/pages/Login.vue src/pages/Register.vue src/components/auth/OtpField.vue test/auth/pages.test.ts && git commit -m "feat(auth): add role-selective login and registration"`

Expected: focused frontend tests and type check pass.

## Task 7: Browser acceptance, production build, and integration verification

**Files:**
- Modify: `e2e/auth.spec.ts`
- Modify: `docs/audits/2026-08-24-role-selective-sms-authentication-verification.md`
- Test: `e2e/auth.spec.ts`

**Interfaces:**
- Consumes: contract-faithful mock identity API and role-aware frontend routes.
- Produces: repeatable browser evidence for student onboarding, teacher workspace, researcher workspace, and pending review behavior.

- [ ] **Step 1: Write failing end-to-end role-routing tests**

```typescript
test('approved teacher login opens the teacher workspace, not overview', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('进入身份').selectOption('teacher')
  await completeMockSmsLogin(page)
  await expect(page).toHaveURL(/\/teacher\/today$/)
})

test('pending teacher registration opens review status, not overview', async ({ page }) => {
  await page.goto('/register')
  await page.getByLabel('注册身份').selectOption('teacher')
  await completeMockRegistration(page, { organization: '示例中学' })
  await expect(page).toHaveURL(/\/identity\/pending$/)
})
```

- [ ] **Step 2: Run the browser tests to verify they fail**

Run: `npm run e2e:mock -- e2e/auth.spec.ts`

Expected: FAIL before the mock/UI work is complete because the requested selectors and routes do not exist.

- [ ] **Step 3: Update mock fixtures only as required by the browser contract**

Add deterministic query- or request-body-driven mock responses for student, teacher, researcher, and pending role scenarios. Do not add browser-only production branches.

- [ ] **Step 4: Run full frontend and backend acceptance suites**

Run: `npm test`

Run: `npm run typecheck`

Run: `npm run build`

Run: `npm run e2e:mock -- e2e/auth.spec.ts`

Run: `pytest -q tests/identity/test_login_onboarding.py tests/identity/test_passwords.py tests/identity/test_sessions.py tests/identity/test_sms_challenges.py tests/identity/test_auth_config.py tests/identity/test_auth_compatibility.py tests/identity/test_role_applications.py tests/identity/test_authorization.py`

Run: `git diff --check`

Expected: every command passes. If a pre-existing unrelated full-suite failure appears, record its exact command and failure in the verification report without modifying unrelated code.

- [ ] **Step 5: Record verification evidence and commit it**

Include command, date, result, and any intentional limitation: real Tencent delivery requires deployment-only credentials and an approved Tencent signature/template, so automated verification uses a fake SDK client rather than a real SMS send.

Run: `git add e2e/auth.spec.ts docs/audits/2026-08-24-role-selective-sms-authentication-verification.md && git commit -m "test(auth): verify role-selective authentication journeys"`

Expected: the commit contains browser acceptance coverage and recorded evidence only.
