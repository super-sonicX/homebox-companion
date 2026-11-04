# Contribution and Review Standards

These are **mandatory working standards** for the maintained `super-sonicX/homebox-companion` fork. They apply to contributors, maintainers, automated agents and future upstream integrations.

## Required workflow for every change

1. **Create a branch and open a pull request.** All changes destined for `main` must be submitted through a GitHub pull request, including feature work, bug fixes, refactoring, documentation, configuration and deployment-related source changes. **Do not commit or push directly to `main`.**
2. **Validate before requesting merge.** Run the relevant automated tests, lint/type checks and regression checks, and document the results in the PR. Protect existing Homebox Companion customisations and compatibility with the running Homebox environment.
3. **Request and complete a CodeRabbit review.** CodeRabbit review is mandatory for every PR and must complete successfully against its **final head commit**. Opening the PR or triggering CodeRabbit is not enough: wait for the completed review and read all findings and follow-up comments. If the bot does not review automatically, request or re-request a CodeRabbit review; never merge a PR whose current head has not been reviewed.
4. **Triage and follow up on every finding.** Apply the [upstream-compatible review triage policy](docs/review-triage-upstream.md) to distinguish fork-introduced defects, necessary integration fixes, unrelated upstream defects, and critical/high-impact risks. Fix confirmed fork-introduced or integration-blocking defects and critical/high-impact risks **on the PR branch, before merge**. For unrelated, pre-existing upstream defects assessed as not high/critical, document evidence from the earlier upstream revision that the defect predates the PR, then defer rather than modifying upstream code unnecessarily. Add tests for fixes and push them to the same PR.
5. **Re-review and verify.** After every new commit to an already-reviewed PR, rerun affected tests and obtain a completed CodeRabbit review covering the updated head commit, including all substantive fixes. Follow up on any new findings. Explicitly document false positives or intentionally declined suggestions with a technical justification; never silently ignore or dismiss them.
6. **Merge only after final-head review and evidence-backed dispositions.** A PR can be merged only when CodeRabbit has successfully reviewed the **current final head commit**, every finding has a recorded disposition supported by provenance and impact evidence, confirmed fork-introduced or integration-blocking defects and high/critical risks have been fixed, relevant tests pass, and required human/CI approvals are satisfied. Unrelated, pre-existing upstream defects assessed as not high/critical may be deferred with evidence; unknown/unassessed findings or unresolved blocking defects may not.
7. **Deploy only reviewed, merged commits.** Production Docker images must be built from the reviewed, merged fork commit, with the existing backup, health-check and rollback process described in [fork maintenance](docs/fork-maintenance.md).

## Required pre-merge checklist

- [ ] Changes are on a feature/fix/docs branch and submitted in a PR targeting `main`.
- [ ] Appropriate automated tests and checks have passed (results recorded in the PR).
- [ ] CodeRabbit has completed a review of the **latest PR head commit**, including all commits made after earlier reviews.
- [ ] Every CodeRabbit finding was investigated and followed up.
- [ ] Confirmed fork-introduced, required integration, and high/critical issues were fixed and tested on the PR branch.
- [ ] Unrelated, pre-existing upstream issues assessed as not high/critical and non-actionable / false-positive findings have documented, evidence-based dispositions.
- [ ] After every new PR commit, affected tests were rerun and CodeRabbit completed a fresh review of the updated head.
- [ ] Every finding has an evidence-backed disposition, no provenance/impact is unassessed, and no fork-introduced errors, required integration defects, or high/critical risks remain unresolved before merge.

## Applicability and enforcement

This policy applies **from its publication onward**. It is introduced through a reviewed pull request. All future changes, including changes to these standards, must go through the same review gates; there are no routine direct-to-`main` exceptions.

Repository settings should also require pull requests and applicable status checks on `main` where available. The documented policy is mandatory even if GitHub branch protections or CodeRabbit's automated status checks are not yet configured to enforce it technically.
