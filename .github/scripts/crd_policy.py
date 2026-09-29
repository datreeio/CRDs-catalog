"""Read-only policy evaluator. Never check out or execute contributor code."""
import base64
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

MAX_FILES = 25
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 10 * 1024 * 1024
MAX_SOURCE = 10 * 1024 * 1024
MAX_SOURCE_TOTAL = 50 * 1024 * 1024
PATH = re.compile(r"([a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)/([a-z0-9]+)_(v[0-9]+(?:(?:alpha|beta)[0-9]+)?)\.json\Z")
SOURCE = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/blob/([0-9a-f]{40})/([A-Za-z0-9_./-]+)\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")


class PolicyError(Exception):
    def __init__(self, decision, reason):
        self.decision, self.reason = decision, reason
        super().__init__(reason)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class GitHub:
    def __init__(self, repository, token=None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid repository")
        self.repository = repository
        self.token = token
        self.cache = {}

    def request(self, path, data=None, method=None, limit=16 * 1024 * 1024):
        if not path.startswith("/") or ".." in path or "#" in path:
            raise ValueError("Invalid API path")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "crds-catalog-policy"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        payload = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request("https://api.github.com" + path, data=payload, headers=headers, method=method)
        with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as response:
            raw = response.read(limit + 1)
        if len(raw) > limit:
            raise PolicyError("manual-review", "A GitHub response exceeds the safe processing limit.")
        return json.loads(raw) if raw else None

    def get(self, path):
        if path not in self.cache:
            self.cache[path] = self.request(path)
        return self.cache[path]

    def pages(self, path, max_pages=30):
        result = []
        for page in range(1, max_pages + 1):
            batch = self.request(path + ("&" if "?" in path else "?") + f"per_page=100&page={page}")
            result.extend(batch)
            if len(batch) < 100:
                return result
        raise PolicyError("manual-review", "GitHub pagination exceeded the safe processing limit.")

    def entry(self, repo, commit, path):
        if not SHA.fullmatch(commit):
            raise ValueError("Expected immutable commit")
        parts = path.split("/")
        if any(p in ("", ".", "..") for p in parts):
            raise ValueError("Invalid file path")
        tree = commit
        for i, part in enumerate(parts):
            response = self.get(f"/repos/{repo}/git/trees/{tree}")
            if response.get("truncated"):
                raise PolicyError("manual-review", "GitHub returned an incomplete file tree.")
            entries = [e for e in response["tree"] if e["path"] == part]
            if len(entries) != 1:
                raise PolicyError("needs-contributor-input", "A supplied source file could not be found at its pinned commit.")
            entry = entries[0]
            if i < len(parts) - 1:
                if entry["type"] != "tree" or entry["mode"] != "040000":
                    raise PolicyError("manual-review", "A file path traverses a symlink or non-directory.")
                tree = entry["sha"]
        return entry

    def blob(self, repo, entry, maximum):
        if entry["type"] != "blob" or entry["mode"] != "100644":
            raise PolicyError("manual-review", "Only regular, non-executable files qualify for auto-merge.")
        if entry.get("size", maximum + 1) > maximum:
            raise PolicyError("manual-review", "A file exceeds the configured size limit.")
        result = self.get(f"/repos/{repo}/git/blobs/{entry['sha']}")
        if result.get("encoding") != "base64":
            raise PolicyError("manual-review", "GitHub did not return the complete file content.")
        raw = base64.b64decode(result["content"])
        if len(raw) != entry["size"] or len(raw) > maximum:
            raise PolicyError("manual-review", "File content size did not match its metadata.")
        return raw


def snapshot(pr):
    values = [pr["head"]["sha"], pr["base"]["sha"], pr["base"]["ref"], pr.get("body") or "", pr["state"], pr["draft"]]
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def walk(value):
    stack = [(value, 0)]
    count = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if depth > 100 or count > 500000:
            raise PolicyError("manual-review", "Document complexity exceeds the safe processing limit.")
        yield item
        if isinstance(item, dict):
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item)


def validate_schema(raw):
    from jsonschema import Draft4Validator, Draft6Validator, Draft7Validator, Draft201909Validator, Draft202012Validator
    from jsonschema.exceptions import SchemaError
    try:
        schema = json.loads(raw, object_pairs_hook=unique_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite number")))
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ValueError("Schema root must have type object")
        for item in walk(schema):
            if isinstance(item, dict):
                for key in ("$ref", "$dynamicRef", "$recursiveRef"):
                    if key in item and (not isinstance(item[key], str) or not item[key].startswith("#")):
                        raise ValueError("External schema references are not permitted")
                # External identifiers can change how local references resolve.
                for key in ("$id", "id"):
                    if key in item and isinstance(item[key], str) and not item[key].startswith("#"):
                        raise ValueError("Non-local schema identifiers require review")
        validators = [Draft4Validator, Draft6Validator, Draft7Validator, Draft201909Validator, Draft202012Validator]
        by_uri = {v.META_SCHEMA.get("$id", v.META_SCHEMA.get("id")): v for v in validators}
        uri = schema.get("$schema")
        validator = Draft7Validator if uri is None else by_uri.get(uri)
        if validator is None:
            raise ValueError("Unsupported JSON Schema dialect")
        validator.check_schema(schema)
        return schema
    except (ValueError, SchemaError, RecursionError, UnicodeError):
        raise PolicyError("needs-contributor-input", "A schema is invalid, has duplicate keys, an unsupported dialect, or an external reference/identifier. Correct the schema and push an update.") from None


def parse_sources(body, filenames):
    blocks = re.findall(r"^```crd-sources\s*\n(.*?)^```\s*$", body or "", re.M | re.S)
    tables = re.findall(
        r"^\|[ \t]*Schema file[ \t]*\|[ \t]*Source CRD[ \t]*\|[ \t]*\n"
        r"\|[ \t]*:?-{3,}:?[ \t]*\|[ \t]*:?-{3,}:?[ \t]*\|[ \t]*\n"
        r"((?:\|[^\n]*\|[ \t]*(?:\n|$))+)", body or "", re.M)
    if len(blocks) + len(tables) != 1:
        raise PolicyError("needs-contributor-input", "Fill one source table with columns Schema file and Source CRD, listing every changed schema and its permanent upstream CRD link. The older crd-sources JSON format is also supported; use only one format. See CONTRIBUTING.md.")
    try:
        if blocks:
            mapping = json.loads(blocks[0], object_pairs_hook=unique_object)
        else:
            pairs = []
            for row in tables[0].splitlines():
                cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
                if len(cells) != 2:
                    raise ValueError()
                pairs.append(tuple(cell[1:-1] if cell.startswith("`") and cell.endswith("`") else cell for cell in cells))
            mapping = unique_object(pairs)
        if not isinstance(mapping, dict) or set(mapping) != set(filenames):
            raise ValueError()
        result = {}
        for filename, url in mapping.items():
            match = SOURCE.fullmatch(url) if isinstance(url, str) else None
            if not match or any(p in ("", ".", "..") for p in match[4].split("/")):
                raise ValueError()
            if any(p in (".", "..") for p in match.group(1, 2)):
                raise ValueError()
            result[filename] = (match[1] + "/" + match[2], match[3], match[4])
        return result
    except (ValueError, TypeError):
        raise PolicyError("needs-contributor-input", "List each changed schema exactly once with its permanent GitHub source CRD link. Open the original CRD file on GitHub, press y, and copy the resulting URL. Branch and tag links do not qualify.") from None


def source_identities(raw):
    import yaml
    try:
        # Disable aliases entirely to prevent alias expansion/cycles and limit work.
        if any(isinstance(t, yaml.tokens.AliasToken) for t in yaml.scan(raw)):
            raise ValueError("YAML aliases")
        documents = list(yaml.safe_load_all(raw))
        identities = set()
        for document in documents:
            for _ in walk(document):
                pass
            if not isinstance(document, dict):
                continue
            candidates = document.get("items", []) if document.get("kind") == "List" else [document]
            for crd in candidates:
                if not isinstance(crd, dict) or crd.get("kind") != "CustomResourceDefinition":
                    continue
                if crd.get("apiVersion") not in ("apiextensions.k8s.io/v1", "apiextensions.k8s.io/v1beta1"):
                    continue
                spec = crd["spec"]
                versions = [v["name"] for v in spec.get("versions", [])]
                if spec.get("version"):
                    versions.append(spec["version"])
                for version in versions:
                    identities.add((spec["group"], spec["names"]["kind"].lower(), version))
        return identities
    except (yaml.YAMLError, ValueError, TypeError, KeyError, RecursionError, UnicodeError):
        raise PolicyError("needs-contributor-input", "A supplied source is not a supported plain CRD YAML/JSON document. Link the CRD file, not a Helm template or project homepage.") from None


def repository_eligible(metadata, now):
    created = dt.datetime.fromisoformat(metadata["created_at"].replace("Z", "+00:00"))
    if metadata["stargazers_count"] < 5 or now - created < dt.timedelta(days=30):
        raise PolicyError("manual-review", "A source repository is less than 30 days old or has fewer than five stars. This PR needs maintainer review; the bot will not wait for the threshold.")
    if metadata.get("private") or metadata.get("disabled"):
        raise PolicyError("manual-review", "Source repositories must be public and accessible.")


def evaluate(api, number, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    pr = api.request(f"/repos/{api.repository}/pulls/{number}")
    report = {"number": number, "head": pr["head"]["sha"], "snapshot": snapshot(pr), "decision": "manual-review", "reason": ""}
    try:
        if pr["state"] != "open" or pr["draft"] or pr["base"]["ref"] != "main":
            raise PolicyError("manual-review", "Only open, ready-for-review PRs targeting main qualify.")
        if not 1 <= pr["changed_files"] <= MAX_FILES:
            raise PolicyError("manual-review", "Auto-merge permits 1 to 25 added or modified schema files.")
        files = api.pages(f"/repos/{api.repository}/pulls/{number}/files", max_pages=1)
        if len(files) != pr["changed_files"]:
            raise PolicyError("manual-review", "The complete PR file list could not be verified.")
        paths = [f["filename"] for f in files]
        if any(f["status"] not in ("added", "modified") or not PATH.fullmatch(f["filename"]) for f in files):
            raise PolicyError("manual-review", "Only added/modified GROUP/kind_version.json files qualify. Deletions, renames, scripts, workflow changes, and other paths need review.")
        total = 0
        head_repo = pr["head"]["repo"]["full_name"]
        for file in files:
            entry = api.entry(head_repo, pr["head"]["sha"], file["filename"])
            if entry["sha"] != file["sha"]:
                raise PolicyError("needs-contributor-input", "The PR changed while being checked; rerun the workflow.")
            raw = api.blob(head_repo, entry, MAX_FILE)
            total += len(raw)
            if total > MAX_TOTAL:
                raise PolicyError("manual-review", "Changed schema files exceed 10 MiB in total.")
            validate_schema(raw)
            # Check original modes as well, including symlink-to-regular transitions.
            if file["status"] == "modified":
                old = api.entry(api.repository, pr["base"]["sha"], file["filename"])
                if old["type"] != "blob" or old["mode"] != "100644":
                    raise PolicyError("manual-review", "Changes involving unusual original file modes need review.")
        mapping = parse_sources(pr.get("body"), paths)
        source_cache, source_total = {}, 0
        for filename, (repo, commit, path) in mapping.items():
            repository_eligible(api.get(f"/repos/{repo}"), now)
            key = (repo, commit, path)
            if key not in source_cache:
                entry = api.entry(repo, commit, path)
                raw = api.blob(repo, entry, MAX_SOURCE)
                source_total += len(raw)
                if source_total > MAX_SOURCE_TOTAL:
                    raise PolicyError("manual-review", "Source CRDs exceed the 50 MiB processing limit.")
                source_cache[key] = source_identities(raw)
            identity = PATH.fullmatch(filename).groups()
            if identity not in source_cache[key]:
                raise PolicyError("needs-contributor-input", f"The source CRD does not match the group, kind, and API version of {filename}.")
        fresh = api.request(f"/repos/{api.repository}/pulls/{number}")
        if snapshot(fresh) != report["snapshot"]:
            raise PolicyError("needs-contributor-input", "The PR changed while being checked; the next run will recheck it.")
        report.update(decision="eligible", reason=f"All lightweight policy checks passed: {len(files)} schema files, {total} bytes.")
    except PolicyError as exc:
        report.update(decision=exc.decision, reason=exc.reason)
    except urllib.error.HTTPError as exc:
        report.update(decision="error", reason=f"GitHub returned HTTP {exc.code}. No approval or merge was attempted. Check source URLs and workflow access, then rerun.")
    return report


def main():
    api = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ.get("GH_TOKEN"))
    number = int(os.environ["PR_NUMBER"])
    report = evaluate(api, number)
    encoded = json.dumps(report, separators=(",", ":"))
    print(encoded)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write("report=" + encoded + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write(f"## PR #{number}: {report['decision']}\n\n{report['reason']}\n")


if __name__ == "__main__":
    main()
