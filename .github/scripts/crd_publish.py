"""Privileged publisher: uses a report from the read-only job, never PR files."""
import json
import os
import time
import urllib.error
from crd_policy import GitHub, SHA, snapshot

MARKER = "<!-- crds-catalog-policy-v1 -->"
REVIEW_MARKER = "CRDs catalog lightweight policy approval"
LABELS = {"needs-contributor-input": ("crd: needs source or fix", "FBCA04"), "manual-review": ("crd: manual review", "D93F0B"), "eligible": ("crd: auto-merge eligible", "0E8A16"), "error": ("crd: check error", "B60205")}


def withdraw(api, number):
    # Only this workflow's own latest decisive review; never human reviews.
    reviews = api.pages(f"/repos/{api.repository}/pulls/{number}/reviews")
    owned = [r for r in reviews if r["user"]["login"] == "github-actions[bot]"
             and r.get("body", "").startswith(REVIEW_MARKER)
             and r["state"] in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED")]
    if not owned or owned[-1]["state"] != "APPROVED":
        return
    review = owned[-1]
    try:
        api.request(f"/repos/{api.repository}/pulls/{number}/reviews/{review['id']}/dismissals", {"message": "Withdrawing automation approval before re-evaluation or after an incomplete merge."}, "PUT")
    except urllib.error.HTTPError as exc:
        if exc.code != 403:
            raise
        # Some repositories restrict dismissals to the owner. Supersede our own
        # approval without expanding anyone's ability to dismiss human reviews.
        api.request(f"/repos/{api.repository}/pulls/{number}/reviews", {
            "event": "REQUEST_CHANGES",
            "body": REVIEW_MARKER + ": withdrawn. Recheck the policy before merging. An eligible rerun will approve again; a maintainer can dismiss this review for a manual exception."
        })


def announce(api, report):
    number, decision = report["number"], report["decision"]
    prefix = f"/repos/{api.repository}"
    label, color = LABELS[decision]
    try:
        api.request(prefix + "/labels", {"name": label, "color": color})
    except urllib.error.HTTPError as exc:
        if exc.code != 422:
            raise
    current = api.pages(prefix + f"/issues/{number}/labels")
    for item in current:
        if item["name"] in {v[0] for v in LABELS.values()} and item["name"] != label:
            from urllib.parse import quote
            api.request(prefix + f"/issues/{number}/labels/" + quote(item["name"], safe=""), method="DELETE")
    api.request(prefix + f"/issues/{number}/labels", {"labels": [label]})
    explanation = {
        "needs-contributor-input": "Please update the PR description or schema files as described below. Editing the description or pushing a fix reruns the checks automatically; maintainer review is not required just to fix missing input.",
        "manual-review": "This PR needs maintainer review. The bot will not approve it or wait for repository age/star thresholds.",
        "eligible": "The lightweight policy passed. Auto-merge still requires GitHub's existing branch protections and checks to permit it.",
        "error": "The policy could not finish. No automatic approval or merge is permitted until a successful rerun.",
    }[decision]
    body = f"{MARKER}\n### CRD contribution: {decision}\n\n{report['reason']}\n\n{explanation}\n\nSee [contribution instructions](https://github.com/{api.repository}/blob/main/CONTRIBUTING.md).\n\nChecked commit: `{report['head']}`."
    comments = api.pages(prefix + f"/issues/{number}/comments")
    owned = [c for c in comments if c["user"]["login"] == "github-actions[bot]" and c.get("body", "").startswith(MARKER)]
    if owned:
        if owned[-1]["body"] != body:
            api.request(prefix + f"/issues/comments/{owned[-1]['id']}", {"body": body}, "PATCH")
    else:
        api.request(prefix + f"/issues/{number}/comments", {"body": body})
    api.request(prefix + "/check-runs", {"name": "CRD auto-merge policy", "head_sha": report["head"], "status": "completed", "conclusion": "success" if decision == "eligible" else "action_required", "output": {"title": decision, "summary": report["reason"]}})


def publish(api, report, trusted_sha, enabled):
    number = report["number"]
    if type(number) is not int or number < 1 or report["decision"] not in LABELS or not SHA.fullmatch(report["head"]):
        raise ValueError("Invalid policy report")
    prefix = f"/repos/{api.repository}"
    pr = api.request(prefix + f"/pulls/{number}")
    if pr["state"] != "open":
        return
    # Always revoke previous bot approvals first, including after body-only edits.
    # If both withdrawal mechanisms fail, stop without publishing or merging.
    withdraw(api, number)
    if snapshot(pr) != report["snapshot"]:
        print("PR changed after validation. No approval or merge.")
        return
    announce(api, report)
    if report["decision"] != "eligible" or not enabled:
        print("No merge: manual/input/error outcome, or CRD_AUTO_MERGE_ENABLED is not true.")
        return
    current_main = api.request(prefix + "/git/ref/heads/main")["object"]["sha"]
    if current_main != trusted_sha:
        print("Main changed since the trusted workflow code was loaded. Rerun required.")
        return
    # No queued native auto-merge: each merge is an immediate, exact-head attempt.
    # This avoids leaving a queued merge behind when the source mapping changes.
    approved = False
    merged = False
    try:
        fresh = api.request(prefix + f"/pulls/{number}")
        if snapshot(fresh) != report["snapshot"] or fresh.get("mergeable") is False:
            return
        api.request(prefix + f"/pulls/{number}/reviews", {"commit_id": report["head"], "event": "APPROVE", "body": REVIEW_MARKER + ": " + report["snapshot"]})
        approved = True
        # GitHub can take a few seconds to recalculate review/merge state.
        for attempt in range(6):
            fresh = api.request(prefix + f"/pulls/{number}")
            if snapshot(fresh) != report["snapshot"]:
                return
            try:
                result = api.request(prefix + f"/pulls/{number}/merge", {"sha": report["head"], "merge_method": "squash"}, "PUT")
                merged = bool(result.get("merged"))
                if merged:
                    print(f"Merged PR #{number} at validated head {report['head']}.")
                    return
            except urllib.error.HTTPError as exc:
                if exc.code not in (405, 409):
                    raise
                if exc.code == 409:
                    return
            if attempt < 5:
                time.sleep(5)
        print("GitHub branch protections blocked the merge. Approval will be withdrawn; rerun when checks/reviews are ready.")
    finally:
        if approved and not merged:
            withdraw(api, number)


def main():
    api = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
    encoded = os.environ.get("POLICY_REPORT")
    if encoded:
        report = json.loads(encoded)
    else:
        number = int(os.environ["PR_NUMBER"])
        pr = api.request(f"/repos/{api.repository}/pulls/{number}")
        report = {"number": number, "head": pr["head"]["sha"], "snapshot": snapshot(pr), "decision": "error", "reason": "The read-only validator did not complete. See the workflow logs and rerun; no merge is authorized."}
    publish(api, report, os.environ["TRUSTED_SHA"], os.environ.get("MERGE_ENABLED") == "true")


if __name__ == "__main__":
    main()
