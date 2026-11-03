# Contribution and Review Standards

These are **mandatory working standards** for the maintained `super-sonicX/homebox-companion` fork. They apply to contributors, maintainers, automated agents and future upstream integrations.

## Required workflow for every change

1. **Create a branch and open a pull request.** All changes destined for `main` must be submitted through a GitHub pull request, including feature work, bug fixes, refactoring, documentation, configuration and deployment-related source changes. **Do not commit or push directly to `main`.**
2. **Validate before requesting merge.** Run the relevant automated tests, lint/type checks and regression checks, and document the results in the PR. Protect existing Homebox Companion customisations and compatibility with the running Homebox environment.
3. **Request and complete a CodeRabbit review.** CodeRabbit review is mandatory for every PR. Opening the PR or triggering CodeRabbit is not enough: **wait until the review has completed**, and read all findings and follow-up comments. If the bot does not review automatically, request or re-request a CodeRabbit review; do not merge an unreviewed PR.
4. **Follow up on every actionable finding.** Investigate each CodeRabbit finding. Fix confirmed defects, regressions, security problems and other actionable errors **on the PR branch, before merge**. Add tests where appropriate and push the fixes to the same PR.
5. **Re-review and verify.** After fixes, rerun affected tests and request an updated CodeRabbit review when changes materially affect the reviewed code or findings remain. Ensure newly reported findings are also addressed. Explicitly document any false positives or intentionally declined suggestions with a technical justification; do not silently ignore or dismiss them.
6. **Merge only after review and remediation.** A PR can be merged only when CodeRabbit has completed its review, all actionable findings have been fixed or explicitly justified, relevant tests pass, and any other required human/CI approvals are satisfied. Unresolved known errors block merge.
7. **Deploy only reviewed, merged commits.** Production Docker images should be built from the merged fork commit, with the existing backup, health-check and rollback process described in [fork maintenance](docs/fork-maintenance.md).

## Required pre-merge checklist

- [ ] Changes are on a feature/fix/docs branch and submitted in a PR targeting `main`.
- [ ] Appropriate automated tests and checks have passed (results recorded in the PR).
- [ ] CodeRabbit has completed a review of the PR.
- [ ] Every CodeRabbit finding was investigated and followed up.
- [ ] All confirmed issues were corrected, tested and pushed to the PR branch.
- [ ] Any non-actionable / false-positive findings have an explicit written rationale.
- [ ] Changes made after review have been re-reviewed where appropriate.
- [ ] No actionable errors or blocking review findings remain before merge.

## Applicability and enforcement

This policy applies **from its publication onward**. The initial publication of this standards file is a **one-time, user-authorised exception** committed directly to `main` so the policy is easy to discover. It is **not** permission for future direct commits.

Repository settings should also require pull requests and applicable status checks on `main` where available. The documented policy is mandatory even if GitHub branch protections or CodeRabbit's automated status checks are not yet configured to enforce it technically.
