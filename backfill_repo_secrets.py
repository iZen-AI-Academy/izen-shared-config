#!/usr/bin/env python3
"""One-time backfill: push MOODLE_URL/MOODLE_TOKEN onto existing private
student repos that predate the per-repo-secret fix in provision_repos.py.

These repos were created while relying on the org-level MOODLE_URL/
MOODLE_TOKEN secrets, which (on GitHub's Free plan) are never actually passed
to private repos -- so their Moodle sync step has been silently failing.
This script finds every repo matching a known private-assignment prefix and
sets the same repo-level secrets provision_repos.py sets for new repos.

Usage:
    python backfill_repo_secrets.py [--dry-run]

Requires the same env vars as provision_repos.py: PROVISION_PAT, MOODLE_URL,
MOODLE_TOKEN.
"""
import argparse
import os
import sys

from github import Auth, Github

from provision_repos import ORG, set_private_repo_secrets

# Prefixes of assignments known to be private (see ASSIGNMENT_CONFIG in
# provision_repos.py). fm3-python-programming-* is deliberately excluded --
# it's public, so it was never affected. Includes both pandas prefixes still
# in use (fm4-pandas-* and the older fm5-pandas-*).
PRIVATE_REPO_PREFIXES = (
    "fm4-numpy-",
    "fm4-pandas-",
    "fm5-pandas-",
    "fm8-feature-engineering-",
)


def find_private_assignment_repos(gh: Github) -> list[str]:
    org = gh.get_organization(ORG)
    names = []
    for repo in org.get_repos():
        if repo.private and repo.name.startswith(PRIVATE_REPO_PREFIXES):
            names.append(repo.name)
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("PROVISION_PAT")
    if not token:
        sys.exit("PROVISION_PAT env var is required")
    if not args.dry_run and not (os.environ.get("MOODLE_URL") and os.environ.get("MOODLE_TOKEN")):
        sys.exit("MOODLE_URL and MOODLE_TOKEN env vars are required (unless --dry-run)")

    gh = Github(auth=Auth.Token(token))
    repo_names = find_private_assignment_repos(gh)
    print(f"found {len(repo_names)} private assignment repos")

    for repo_name in repo_names:
        if args.dry_run:
            print(f"[dry-run] would set repo secrets on {repo_name}")
            continue
        set_private_repo_secrets(token, repo_name)

    print(f"\ndone: {len(repo_names)} repos processed")


if __name__ == "__main__":
    main()
