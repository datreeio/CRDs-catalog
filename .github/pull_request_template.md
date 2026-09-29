## What changed?

Briefly describe the schemas you added or updated.

## For humans: where did the schemas come from?

For each schema you changed, add a row below linking to the original CRD file.

**How to get the link:** Open the original CRD YAML or JSON file on GitHub, press **y**, then copy the address from your browser. This saves a link to that exact revision of the file.

Replace the example row. If one CRD file covers several schemas, use the same link in each row.

| Schema file | Source CRD |
| --- | --- |
| `example.io/widget_v1.json` | Paste the permanent GitHub file link here |

The bot will check your PR and tell you if anything needs fixing. Edit this description or push a fix to run the checks again.

[Contribution guide and automatic merge limits](https://github.com/datreeio/CRDs-catalog/blob/main/CONTRIBUTING.md)

<details>
<summary>For agents: copy this prompt to your coding agent</summary>

```text
Help me finish this CRDs-catalog pull request.

Read https://github.com/datreeio/CRDs-catalog/blob/main/CONTRIBUTING.md.
Check the schemas I added or updated. Find their original upstream CRD files
and get permanent GitHub links pinned to full commit SHAs. Confirm that the
sources contain the matching group, kind, and API version.

Fill the source table in this PR description, with one row per changed schema.
Keep the column names "Schema file" and "Source CRD". Use the schema's path in
this repository and the full source URL. Reuse a URL if it covers multiple files.
Do not invent links. If a source is unavailable, tell me what is missing.

Check the contribution requirements and fix any issues the bot reports.
Explain any exceptions that need maintainer review. Only change the requested
schemas and this PR description.
```

</details>
