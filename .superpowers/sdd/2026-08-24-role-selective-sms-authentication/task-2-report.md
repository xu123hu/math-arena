# Task 2 — Role-selective SMS registration report

## Changes

- Added `registration` as a permitted SMS challenge purpose, without changing the other purposes.
- Added `POST /api/auth/register/sms` with purpose-bound challenge consumption and role-specific request validation.
- Added an atomic `IdentityService.register_sms` flow. It creates or reuses the base identity, creates exactly one approved student binding, records the supplied platform-terms consent, and serializes professional registration against the identity row.
- Professional registration creates or reuses one pending application and pending professional binding, then issues a student-only session with `pending_role`. The response includes the pending-review state and application summary.
- Added API coverage for student and teacher registration, login-purpose challenge rejection, required researcher direction, consent persistence, student-only professional session issuance, and duplicate-registration reuse. Added challenge lifecycle coverage for the new `registration` purpose.

## RED evidence

Before production changes, ran:

```text
pytest -q tests/identity/test_login_onboarding.py -k "registration"
```

Result after correcting the real SMS-provider fixture setup:

```text
FFFFF.                                                                   [100%]
5 failed, 1 passed, 3 deselected
```

Each API test failed because `POST /api/auth/register/sms` did not yet exist (`404 Not Found`): student registration, teacher pending application, login-purpose mismatch handling, researcher field validation, and duplicate professional resubmission.

## GREEN evidence

After the minimal implementation, the focused regression command produced:

```text
......                                                                   [100%]
6 passed, 3 deselected in 3.75s
```

## Final command output

```text
pytest -q tests/identity/test_login_onboarding.py tests/identity/test_sms_challenges.py
........................                                                 [100%]
24 passed in 5.64s

python -m ruff check app/domains/identity/challenges.py app/domains/identity/router.py app/domains/identity/service.py tests/identity/test_login_onboarding.py tests/identity/test_sms_challenges.py
All checks passed!

python -m ruff format --check app/domains/identity/challenges.py app/domains/identity/router.py app/domains/identity/service.py tests/identity/test_login_onboarding.py tests/identity/test_sms_challenges.py
5 files already formatted

git diff --check
exit 0
```

## Self-review

- The registration endpoint consumes only `registration` challenges; a login challenge produces `AUTH_CHALLENGE_PURPOSE_MISMATCH`.
- Request validation restricts roles to student, teacher, and researcher; professional roles require an organization and researchers also require a research direction.
- The service uses PostgreSQL upserts and a locked base user row, so repeat or concurrent registration cannot create duplicate identities, student bindings, or pending professional applications.
- Professional sessions are explicitly issued with `active_role="student"` and `pending_role` set to the requested professional role. No professional session is created before approval.
- The changed files are limited to the five task files named in the brief.

## Concerns

- The existing `/api/auth/login/sms` route still invokes its legacy `login_sms` creation behavior. This task deliberately leaves that legacy endpoint untouched because the brief assigns the normal-login behavior change to Task 3; Task 3 should remove that remaining path to fully enforce the global “only `/register/sms` creates an initial student binding” invariant.
