# Contributing schemas

## For humans

1. Add or update JSON schemas at `GROUP/kind_version.json`, for example `example.io/widget_v1.json`. You can use the [CRD Extractor](README.md#crd-extractor) or another generation method.
2. Find the public upstream CRD YAML/JSON file containing the matching group, kind, and API version. On GitHub, press **y** while viewing that file to get a URL pinned to its full commit SHA. A project homepage, branch, tag, Helm template, or cluster export alone is not sufficient.
3. Fill the source table in your PR description. Add one row for **every schema you added or updated**, with its path in this repository and the permanent link to the original CRD file. Repeat a URL if one CRD file covers several schemas. Replace the example row, keeping the column names below.

| Schema file | Source CRD |
| --- | --- |
| `example.io/widget_v1.json` | Paste the permanent GitHub file link here |

Use the full URL in the second column. A permanent link looks like `https://github.com/OWNER/REPO/blob/COMMIT/path/to/crd.yaml`, where `COMMIT` is the full 40-character commit ID. Pressing **y** on the GitHub file page creates this link for you.

Existing PRs may still use a `crd-sources` JSON block mapping schema paths to source URLs. Use either the table or the JSON block, not both.

You do not need to supply a separate project repository, project version, generation command, or generation-tool name.

### What happens next

- **Automatic merge:** All checks pass, the PR is ready for review, and GitHub branch protections permit the merge.
- **Contributor input needed:** The source table is missing or incomplete, the source identity does not match, or a schema needs correction. Edit the PR description or push corrected files. The bot automatically rechecks it.
- **Manual review:** A source repository is younger than 30 days or has fewer than five stars; a file/count/size limit is exceeded; or changes include deletions, renames, scripts, workflows, unusual file modes, or other non-schema files. The bot flags the PR immediately. It does not wait for a repository to become eligible.
- **Check error:** GitHub or another dependency was unavailable. A maintainer can rerun the workflow. This never authorizes a merge.

Automatic merge allows at most **25 added/modified schemas**, **2 MiB per resulting full file**, and **10 MiB combined**. Each source repository must be public, at least **30 days old**, and have at least **five stars**. New groups and changes to schema constraints are welcome.

Schemas must be valid JSON objects with `type: object`, valid JSON Schema, no duplicate keys, and no external schema references or non-local identifiers. Without `$schema`, the validator uses Draft 7. Explicit Draft 4, 6, 7, 2019-09, and 2020-12 dialects are supported.

For bounded processing, source CRDs are limited to 10 MiB each / 50 MiB combined, with no YAML aliases. Very deep or complex documents need manual review. Sources must be plain CRD YAML/JSON, including multi-document YAML or Kubernetes Lists.

The bot checks source group/kind/API version against the catalog filename. It does not independently regenerate schemas or prove that their complete contents match upstream. Repository age and stars are abuse filters, not proof of project authenticity.

## For agents

Copy this prompt to your coding agent:

```text
Prepare a schema contribution to https://github.com/datreeio/CRDs-catalog.

Read CONTRIBUTING.md and the PR template from the repository's main branch.
Add/update only the JSON schemas needed for my requested CRDs, using the
catalog's GROUP/kind_version.json naming convention. Do not change workflows,
scripts, documentation, index.yaml, file modes, or unrelated schemas in this PR.
Do not delete or rename schemas to qualify for automatic merging.

Find the actual public upstream CRD YAML/JSON for each changed schema. Use
GitHub file URLs pinned to full 40-character commit SHAs, not branches/tags,
homepages, generated guesses, or Helm templates. Confirm that each source
contains the schema's group, kind, and API version. Do not substitute a different
repository just to meet the age/star thresholds.

Validate JSON and JSON Schema; do not include duplicate keys or external schema
references. Keep changes within 25 files, 2 MiB per resulting full file and
10 MiB combined. If the requested contribution needs an exception, explain it
and allow maintainer review instead of hiding or splitting changes to evade checks.

Fill one source table in the PR description, with columns "Schema file" and
"Source CRD". List every changed schema path and its full commit-pinned source
CRD URL. Repeat URLs when one source covers multiple schemas. Do not invent source evidence. No separate
repository, project version, or generation-tool fields are required.

Check whether each source repository is at least 30 days old and has at least
five stars. If it does not qualify, state that manual review is needed; do not
wait or try to inflate its stars. If the bot requests a correction, fix the PR
files or source mapping and let the automatic checks rerun.
```

## Maintainer operation

`CRD contribution policy` evaluates PR opens, description edits, new commits, reopenings, and transitions out of draft. It also retries after the listed CI workflows complete for the same head commit. Use its **Run workflow** control with a PR number to recheck an existing PR. Dry run is the default and does not comment, approve, or merge.

Repository variable `CRD_AUTO_MERGE_ENABLED=true` enables approval and merging. Without it, normal runs still report decisions but never approve or merge. Delete the variable or set it to `false` to stop new automatic approvals/merges.

The policy check is informational rather than globally required: maintainers must remain able to review and merge exceptions. Keep the existing required PR approval and stale-approval dismissal protection. Allow GitHub Actions to approve PRs, and permit its app to merge into `main` where branch restrictions require this. Do not grant a PR-review bypass. The bot never bypasses required checks, human change requests, or Code Owner rules.

The validator runs with read-only permissions. The publisher runs separately with write permissions, loads only trusted main-branch code, rechecks the PR snapshot, approves only eligible PRs, and requests a merge with the exact validated head SHA. It withdraws its approval if the merge cannot complete. If review dismissal is restricted, it supersedes its own approval with a changes-requested review; an eligible rerun clears that by approving again, or the owner can dismiss it for a manual exception. Native queued auto-merge is deliberately not used, so a pending merge is not left behind after source information changes. Normal operation needs no PAT, AI service, source registry, or regeneration service.

If a run is forcibly cancelled after approving but before merging, rerun it to withdraw/recheck its approval. A PR body edit cannot be atomically locked with GitHub's merge API; the publisher rechecks immediately before merging, while the API atomically enforces the head SHA.

Merges made with `GITHUB_TOKEN` do not trigger ordinary push workflows. This repository's scheduled index update still runs independently. If a deployment needs a push-triggered run after a bot merge, use an explicit dispatch or a separately configured GitHub App.
