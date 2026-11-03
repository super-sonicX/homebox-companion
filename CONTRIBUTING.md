# Contribution and Review Standards

These are **mandatory working standards** for the maintained `super-sonicX/homebox-companion` fork. They apply to contributors, maintainers, automated agents and future upstream integrations.

## Required workflow for every change

1. **Create a branch and open a pull request.** All changes destined for `main` must be submitted through a GitHub pull request, including feature work, bug fixes, refactoring, documentation, configuration and deployment-related source changes. **Do not commit or push directly to `main`.**
2. **Validate before requesting merge.** Run the relevant automated tests, lint/type checks and regression checks, and document the results in the PR. Protect existing Homebox Companion customisations and compatibility with the running Homebox environment.
3. **Request and complete a CodeRabbit review.** CodeRabbit review is mandatory for every PR. Opening the PR or triggering CodeRabbit is not enough: **wait until the review has completed**, and read all findings and follow-up comments. If the bot does not review automatically, request or re-request a CodeRabbit review; do not merge an unreviewed PR.
4. **Triage and follow up on every finding.** Apply the [upstream-compatible review triage policy](docs/review-triage-upstream.md) to distinguish fork-introduced defects, necessary integration fixes, unrelated upstream defects, and critical/high-impact risks. Fix confirmed fork-introduced or integration-blocking defects and critical/high-impact risks **on the PR branch, before merge**. For unrelated, non-critical upstream defects, document the evidence and defer rather than modifying upstream code unnecessarily. Add tests for fixes and push them to the same PR.
5. **Re-review and verify.** After fixes, rerun affected tests and request an updated CodeRabbit review when changes materially affect the reviewed code or findings remain. Ensure newly reported findings are also addressed. Explicitly document any false positives or intentionally declined suggestions with a technical justification; do not silently ignore or dismiss them.
6. **Merge only after review and disposition.** A PR can be merged only when CodeRabbit has completed its review, all findings have been triaged and followed up, confirmed fork-introduced or integration-blocking defects and high/critical risks have been fixed, other findings have documented dispositions, relevant tests pass, and required human/CI approvals are satisfied. Unrelated non-critical upstream defects may be deferred with evidence; unresolved blocking defects may not.
7. **Deploy only reviewed, merged commits.** Production Docker images should be built from the merged fork commit, with the existing backup, health-check and rollback process described in [fork maintenance](docs/fork-maintenance.md).

## Required pre-merge checklist

- [ ] Changes are on a feature/fix/docs branch and submitted in a PR targeting `main`.
- [ ] Appropriate automated tests and checks have passed (results recorded in the PR).
- [ ] CodeRabbit has completed a review of the PR.
- [ ] Every CodeRabbit finding was investigated and followed up.
- [ ] Confirmed fork-introduced, required integration, and high/critical issues were fixed and tested on the PR branch.
- [ ] Unrelated non-critical upstream issues and non-actionable / false-positive findings have documented, evidence-based dispositions.
- [ ] Changes made after review have been re-reviewed where appropriate.
- [ ] No confirmed fork-introduced errors, required integration defects, or high/critical risks remain unresolved before merge.

## Applicability and enforcement

This policy applies **from its publication onward**. The initial publication of this standards file is a **one-time, user-authorised exception** committed directly to `main` so the policy is easy to discover. It is **not** permission for future direct commits.

Repository settings should also require pull requests and applicable status checks on `main` where available. The documented policy is mandatory even if GitHub branch protections or CodeRabbit's automated status checks are not yet configured to enforce it technically.
