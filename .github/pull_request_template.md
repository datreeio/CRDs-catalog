## Summary

<!-- Briefly describe the schemas added or updated. -->

## Source CRDs

<!-- Map EVERY added/modified schema to a public upstream CRD file pinned to a
full 40-character Git commit. Replace the example below. Repeat a URL if one
source file covers several schemas. Do not use branch/tag URLs or homepages.
No separate repository, project version, or generation-tool field is needed. -->

```crd-sources
{
  "example.io/widget_v1.json": "https://github.com/OWNER/REPO/blob/FULL_40_CHARACTER_COMMIT/config/crd/widget.yaml"
}
```

## For humans

See [contribution instructions](https://github.com/datreeio/CRDs-catalog/blob/main/CONTRIBUTING.md#for-humans). Add the schemas and fill the source mapping above. Missing information can be corrected by editing this description; the bot rechecks automatically.

Auto-merge limits: 25 files, 2 MiB per file, 10 MiB total. Source repositories must be at least 30 days old and have at least five stars. Exceptions go directly to manual review.

## For agents

Copy this prompt to your agent:

```text
Read https://github.com/datreeio/CRDs-catalog/blob/main/CONTRIBUTING.md and follow
its agent instructions for this PR. Add or update only the requested JSON schemas.
Find each actual upstream CRD file and pin its GitHub URL to a full commit SHA.
Verify group, kind, and API version; fill the crd-sources mapping above for every
changed schema. Check JSON Schema validity and the file/size and repository
age/star limits. Do not invent sources or change unrelated files. If an exception
is needed, explain it for manual review. Fix bot-reported missing information
by updating the PR description or files so checks can rerun automatically.
```
