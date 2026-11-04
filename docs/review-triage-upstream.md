# Code-review triage and upstream-compatibility policy

**Applies to:** all reviews and changes in the maintained `super-sonicX/homebox-companion` fork, including CodeRabbit, Codex, human reviews and upstream merges.

## Goal

Keep this fork as close as practical to the original author's `Duelion/homebox-companion` releases while preserving our own inventory, Library and Homebox integration features. **A reviewer finding is a candidate for investigation, not automatic authorisation to change upstream code.** Minimise divergent changes and avoid broad, unrelated refactors.

## Classify every review finding before editing code

| Classification | Decision | Required follow-up |
| --- | --- | --- |
| **Fork-introduced regression or defect** | **Fix in the PR before merge.** | Reproduce; add a regression test; apply the smallest viable fix; re-run affected tests and CodeRabbit. |
| **Upstream defect blocking a fork feature or a required integration** | **Fix only as necessary.** | Confirm it exists upstream, document the dependency, prefer a small isolated compatibility patch, consider reporting it upstream, and track removal when upstream resolves it. |
| **Unrelated pre-existing upstream defect (not high/critical)** | **Normally do not fix in this fork.** | Document the finding and evidence that it predates our change; optionally open/link an upstream issue; explain why it is out of scope. This classification is a documented disposition, not an unreviewed dismissal. |
| **High/critical-impact issue, regardless of origin** | **Fix before merging; immediately contain exposed production systems while preparing that fix. Containment alone does not satisfy the merge gate. Never defer solely because the defect is upstream.** | Verify the risk and exploitability/impact, prioritise minimal safe remediation, regression-test, notify or report upstream where appropriate, and follow the required PR/review process. |
| **False positive / recommendation without a demonstrated issue** | **Do not modify code merely to satisfy the suggestion.** | Record the technical rationale and supporting test, source or documentation. |
| **Optional performance, architecture or stylistic improvement** | **Separate from the current PR.** | Capture as an issue or proposal if valuable; assess upstream compatibility and maintenance cost before proceeding. |

**Risk classification:** use the impact levels **low, medium, high and critical**, based on verified likelihood, reachability and consequences rather than a reviewer badge alone. **Not high/critical** means a substantiated low- or medium-impact finding; only unrelated, pre-existing upstream issues at those levels may be deferred with evidence. **High and critical** issues must be fixed before merging regardless of origin.

**High/critical-impact examples:** exploitable security/privacy weaknesses, credential exposure, destructive or silent data corruption, major availability failures affecting our deployment, and material safety problems. Severity labels are a starting point, not proof: verify the actual affected code, reachable paths and deployment conditions. A reviewer label such as *Major* is not automatically a confirmed high-impact defect, and a lower-labelled issue can still be high-impact.

## Review and decision process

1. **Establish provenance:** compare the reported code against the unmodified upstream base/appropriate upstream release and against the diff in our PR. Determine whether the behaviour existed upstream or came from our fork; do not assume all comments in a PR are newly introduced.
2. **Assess impact:** reproduce when possible, identify affected code paths and inventory data, determine real severity, and check whether the issue affects our configuration. Prioritise high/critical risks irrespective of origin.
3. **Record a decision:** in the PR conversation, mark each issue **fix / minimal compatibility fix / upstream-deferred / false positive / future enhancement**, together with evidence and a brief rationale. Link upstream issues when appropriate.
4. **Keep fixes surgical:** use small, well-contained patches, wrappers, configuration or modules rather than broad rewrites of upstream files. Avoid unnecessary dependency changes and formatting-only churn in unrelated modules.
5. **Validate compatibility:** add regression coverage for changed functionality, run relevant tests and type/lint checks, and test interaction with upstream interfaces. Re-run CodeRabbit after substantive fixes and address new actionable findings.
6. **Merge gate:** do not merge with unresolved confirmed fork-introduced bugs, required integration failures or verified high/critical risks. A documented unrelated, pre-existing upstream defect assessed as not high/critical is not a fork merge blocker when responsibly triaged and deferred.
7. **Deploy only reviewed and merged commits**, with a rollback path and post-deployment verification. Document any emergency mitigation separately and bring its code through a reviewed PR.

## Maintaining compatibility with future upstream releases

- Track the upstream commit/release used as a base, the fork commit and the list of fork-specific patches (PR, purpose, affected files, test coverage, and upstream issue/PR if any).
- Integrate upstream changes in a maintenance branch/PR, never by directly overwriting `main`. Inspect both Git merge conflicts and *semantic* conflicts even when Git merges cleanly.
- When upstream introduces an equivalent feature or fixes a locally patched defect, prefer the upstream implementation and retire the duplicate fork patch after tests.
- Regularly review unresolved upstream-deferred findings and reclassify them if their impact changes. Do not build an expanding backlog of unrelated upstream maintenance into feature PRs.
- Report generally useful defects upstream where sensible; any upstream PR is separate from approval and testing for our fork.

## Critical-issue exception and process safety

Critical/high-impact defects **override the usual preference not to change upstream code**, not the requirement for due diligence or peer review. Emergency containment is temporary and does not authorise merging a PR with an unresolved confirmed high/critical defect. If an immediately exploitable problem requires emergency containment (such as disabling a vulnerable feature or rolling back), act to protect data and service first, record the mitigation, and submit any lasting code fix through the standard PR, CodeRabbit and validation gates. No automatic merge or unreviewed production deployment is authorised by this exception.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the mandatory PR workflow and [fork-maintenance.md](fork-maintenance.md) for upstream integration and deployment safeguards.
