# Role-Selective SMS Authentication Design

## Goal

Allow students, teachers, and researchers to select their intended identity during SMS registration and login. An approved identity must always receive a session for its own workspace. Teacher and researcher access remains subject to administrator review.

## Scope and decisions

- The public registration page offers `student`, `teacher`, and `researcher`.
- A student SMS registration creates an approved student binding and proceeds to student onboarding.
- A teacher or researcher SMS registration creates a normal platform account plus a pending professional role application. It does not grant professional API access before an administrator approves the application.
- The client routes a newly submitted or still-pending professional application to the review-status page, never to the student home as an implicit fallback.
- A login request carries an optional `preferred_role` (`student`, `teacher`, or `researcher`). The server issues a session with that exact role only when the corresponding binding is approved. It never silently substitutes a professional selection with student.
- If the selected professional identity is pending, rejected, suspended, or absent, the response reports that state without issuing a professional session. The UI explains the next action instead of opening a mismatched workspace.
- If no target role is supplied by a legacy caller, the server keeps deterministic compatibility behavior: the user’s approved last active role, otherwise the approved student role, otherwise one approved role in a fixed order. New UI callers always submit a target role.
- Password login receives the same optional `preferred_role` contract so the two authentication methods cannot diverge.
- The legacy `/api/auth/register/teacher` route is retired with a stable `410` response. It must not create a pre-review teacher token. Other legacy code paths stay explicitly deprecated during their existing compatibility window and are not used by the new UI.

## Registration and review flow

1. The registration screen collects a phone number, SMS code, selected role, consent, and the role-specific organization information.
2. It requests an SMS challenge with purpose `registration`; challenge codes remain purpose-bound and single-use.
3. `POST /api/auth/register/sms` consumes that exact challenge.
4. For `student`, the endpoint creates or reuses the approved student identity, issues a student session, and returns `onboarding_required: true`.
5. For `teacher` or `researcher`, it creates or reuses the base identity, creates a `pending` `RoleApplication` and role binding using the existing review state machine, and returns `registration_status: pending_review` plus the requested role. It does not issue an unapproved teacher or researcher token.
6. The existing administrator review endpoints approve, reject, or request more information. Approval activates the role binding and revokes existing sessions as today.
7. On the next login, selecting the approved professional identity produces a teacher or researcher session and the client opens `/teacher/today` or `/research` respectively.

The base account is only the identity required to show the authenticated review flow; it does not confer teacher or researcher authorization. All professional endpoints continue to require an approved active role.

## Login and routing contract

### Request fields

`POST /api/auth/login/sms` and `POST /api/auth/login/password` accept:

```json
{
  "preferred_role": "teacher"
}
```

`preferred_role` is optional for compatibility and is restricted to `student`, `teacher`, and `researcher` on public login pages. It cannot name `admin`.

### Response fields

Successful professional login returns an `active_role` equal to the requested approved role. The frontend redirects from that value directly, rather than first redirecting to `/` and relying on a default.

For a selected role that is not approved, the server returns a stable identity-state result (`pending_review`, `needs_more_info`, `rejected`, or `not_available`) without granting a professional token. The frontend routes `pending_review` and `needs_more_info` to `/identity/pending`; rejected and unavailable identities receive a clear retry or application action.

The router remains defensive: a URL requiring a role checks both the active role and an approved binding. A teacher token cannot load a student route, and a student token cannot load a teacher or research route.

## SMS provider contract

`AUTH_SMS_PROVIDER` has exactly two supported values:

- `demo`: permitted only outside production and only for `AUTH_DEMO_SMS_ALLOWLIST`; the API may return `demo_code`.
- `tencent`: sends through Tencent Cloud SMS SDK 3.0 using a configured SecretId, SecretKey, SDK App ID, approved signature, template ID, region, and JSON template parameter list.

Tencent SMS is configured entirely through environment variables. Template parameters use `{code}` as the only substitution token; for example, `TENCENT_SMS_TEMPLATE_PARAMS=["{code}","5"]`. The provider converts Mainland China phones to E.164 (`+86...`), checks Tencent’s per-recipient delivery status, and maps vendor errors to existing stable application error keys. Provider credentials and vendor messages never enter API responses or logs.

Production startup rejects an unsupported provider, `demo`, malformed template parameters, or incomplete Tencent settings. Real integration follows Tencent Cloud’s current `SendSms` API and SDK 3.0 parameter names (`SmsSdkAppId`, `SignName`, `TemplateId`, `PhoneNumberSet`, and `TemplateParamSet`).

## Frontend behavior

- Login has a target-workspace selector separate from the SMS/password selector.
- Register has a role selector and conditionally shows organization, teaching, or research fields.
- OTP controls use `registration` when registering and `login` when logging in; demo code is displayed only when the server explicitly includes it.
- Pinia keeps the exact returned active role and role-state result. It never infers `student` when a target professional role was chosen.
- The mock server mirrors the same registration and login role contract for student, teacher, researcher, pending, and approved states. Mock mode remains opt-in through `VITE_USE_MOCK=1`.

## Security and error handling

- Professional authority is granted only by an approved `RoleBinding`, never by a client-supplied role, an application row, or a token claim alone.
- Registration codes cannot authenticate login and login codes cannot register an account.
- Login attempts for another role do not add a student binding or mutate role approval state.
- Existing session and refresh authorization checks remain unchanged; an administrator approval revokes prior sessions so the next session reflects the reviewed role set.
- Requests validate role-specific required data before consuming a usable path. Duplicate pending applications return the existing conflict code and leave data unchanged.

## Test and acceptance criteria

Backend tests must prove:

1. Student registration creates one approved student and starts onboarding.
2. Teacher and researcher registration create pending applications and cannot receive professional tokens before approval.
3. An approved teacher SMS login with `preferred_role=teacher` issues `active_role=teacher`; researcher behaves analogously.
4. A selected pending or rejected role neither falls back to a student portal nor changes its approval status.
5. Login never creates a student binding merely because a teacher or researcher logs in.
6. Registration challenges are accepted only for registration.
7. Tencent sender formats a valid request and maps recipient/vendor failures without exposing provider details.
8. Production configuration rejects incomplete Tencent configuration and demo configuration.
9. The retired teacher-registration endpoint does not create users, bindings, sessions, or tokens.

Frontend tests must prove:

1. All three roles are selectable on registration and their required fields are enforced.
2. Login submits the selected target role for both SMS and password paths.
3. An approved teacher and researcher redirect to their respective workspace.
4. A pending professional registration reaches the review page, not `/overview`.
5. Mock identity and mock API responses preserve role-specific routing.

End-to-end verification covers student registration, approved teacher login, approved researcher login, and pending teacher review routing in both real-API contract mode and opt-in mock mode.
