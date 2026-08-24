# Task 3 report — selected-role SMS and password login

## Scope

- Worktree: `D:\worktrees\math-arena-auth`
- Changed only the Task 3 router/service contracts and their three specified test files.
- Did not modify Tencent SMS configuration, legacy-route retirement, or frontend files.

## RED / GREEN evidence

### Cycle 1 — selected role and unknown SMS login

1. Added route-level tests before production changes for an approved teacher SMS selection,
   a pending teacher SMS selection, and an unknown phone.
2. RED command:

   ```text
   pytest -q tests/identity/test_login_onboarding.py -k "preferred_role or teacher_sms_login or unknown_phone"
   ```

   Result: `2 failed, 12 deselected`.

   - Approved-teacher response lacked `identity_status` and always used the student session.
   - Unknown-phone SMS login returned HTTP 200, demonstrating implicit identity creation.
3. Implemented immutable `LoginRoleResolution` and `resolve_login_role`, added strict public
   `preferred_role` request fields, changed SMS login to locate an existing user only, and made
   both login routes issue the resolver's active/pending roles.
4. GREEN command (same focused selection): `3 passed, 11 deselected`.

### Cycle 2 — response role verification

1. During self-review, added a real-response assertion that a pending/rejected researcher is
   not returned as verified.
2. RED command:

   ```text
   pytest -q tests/identity/test_passwords.py -k "selected_nonapproved_professional"
   ```

   Result: `2 failed, 14 deselected`; both non-approved role entries incorrectly had
   `verified: true`.
3. Changed the password response to use `binding.verified`, then expanded the table to also
   cover `needs_more_info`.
4. GREEN command (same focused selection): `3 passed, 14 deselected`.

### Compatibility test updates

The prior onboarding test used `/login/sms` as an implicit registration endpoint. With the new
contract that call correctly returns `AUTH_ROLE_NOT_AVAILABLE`; the test now registers via
`/register/sms` before logging in. Its previous single-consent assertion was adjusted to assert
the onboarding consent by `(version, source)`, preserving the registration consent written by
Task 2.

## Final verification

```text
pytest -q tests/identity/test_login_onboarding.py tests/identity/test_passwords.py tests/identity/test_role_applications.py
# 34 passed in 15.67s

ruff check app/domains/identity/router.py app/domains/identity/service.py tests/identity/test_login_onboarding.py tests/identity/test_passwords.py tests/identity/test_role_applications.py
# All checks passed!

git diff --check
# exit 0
```

## Self-review

- `preferred_role` accepts only `student`, `teacher`, and `researcher`; `admin` cannot enter
  either public login request.
- Resolver returns the exact approved selected role. Non-approved professional targets receive
  only an approved student session with `pending_role` and the status derived from the latest
  application (`pending_review`, `needs_more_info`, or `rejected`).
- An absent explicit professional role and an unknown SMS phone return
  `AUTH_ROLE_NOT_AVAILABLE` (403) before session issuance or binding mutation.
- Legacy calls retain deterministic approved-role fallback:
  `last_active_role`, then student, then teacher/researcher/admin.
- SMS login does not call `IdentityService.login_sms`; new identities must use `/register/sms`.
- Existing role-application transition coverage now proves that approval revokes the temporary
  student session carrying `pending_role=teacher`.

## Test-environment note

The focused pytest runs emit pre-existing asyncpg connection-close traces during fixture teardown
on Windows/Python 3.13. Pytest nevertheless exited successfully for all final verification runs;
these messages did not represent test failures.
