#!/usr/bin/env python3
"""Start head-attached checks for this repository's GITHUB_TOKEN-created PRs.

Run with GH_TOKEN, GITHUB_REPOSITORY and one owned branch prefix. A PAT/App token
can use native PR events instead. Never dispatch fork or human-authored PR code.
"""

import json
import os
import subprocess
import sys


OWNED_PREFIXES = (
    "renovate/",
    "chore/sync-posthog-topics",
    "chore/sync-posthog-user-scripts",
    "chore/posthog-tracker-cursor",
    "agent/tracker-",
)


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", path], text=True))


def main():
    prefix = sys.argv[1]
    if prefix not in OWNED_PREFIXES:
        raise SystemExit("Only explicitly owned bot branch prefixes may be dispatched")
    repo = os.environ["GITHUB_REPOSITORY"]
    base = api(f"repos/{repo}/commits/main")["sha"]
    pages = json.loads(subprocess.check_output(
        ["gh", "api", f"repos/{repo}/pulls?state=open&per_page=100", "--paginate", "--slurp"],
        text=True,
    ))
    stale = []
    for pr in (pr for page in pages for pr in page):
        head = pr["head"]
        if not head["ref"].startswith(prefix):
            continue
        if (head.get("repo") or {}).get("full_name") != repo or pr["user"]["login"] != "github-actions[bot]":
            print(f"Skipping non-owned PR #{pr['number']}")
            continue
        comparison = api(f"repos/{repo}/compare/{base}...{head['sha']}")
        if comparison["status"] not in ("ahead", "identical"):
            stale.append(str(pr["number"]))
            continue
        subprocess.run(
            ["gh", "workflow", "run", "kind-happy-path.yaml", "--repo", repo, "--ref", head["ref"],
             "-f", f"base_sha={base}", "-f", f"expected_head={head['sha']}"],
            check=True,
        )
        print(f"Dispatched release-ready for PR #{pr['number']} head {head['sha']}")
    if stale:
        raise SystemExit("Update/rebase these bot PRs onto current main before dispatch: " + ", ".join(stale))


if __name__ == "__main__":
    main()
