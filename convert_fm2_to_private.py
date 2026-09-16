#!/usr/bin/env python3
"""One-time migration: convert existing FM2 (Python) student repos from
public to private, and push repo-level Moodle secrets onto them.

FM2 was public because that let it get org-level Actions secrets for free
on GitHub's Free plan (see provision_repos.py's module docstring). That
meant students could browse each other's public FM2 repos on GitHub, which
is not desired. ASSIGNMENT_CONFIG now marks FM2 private for new repos;
this script does the one-time flip for repos that already exist.

Usage:
    python convert_fm2_to_private.py [--dry-run]

Requires the same env vars as provision_repos.py: PROVISION_PAT,
MOODLE_URL, MOODLE_TOKEN.
"""
import argparse
import os
import sys

from github import Auth, Github

from provision_repos import ORG, set_private_repo_secrets, set_repo_private

FM2_PREFIX = "fm3-python-programming-"


def find_public_fm2_repos(gh: Github) -> list[str]:
    org = gh.get_organization(ORG)
    return [
        repo.name
        for repo in org.get_repos()
        if not repo.private and not repo.is_template
        and not repo.name.endswith(("-template", "_template"))
        and repo.name.startswith(FM2_PREFIX)
    ]


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
    repo_names = find_public_fm2_repos(gh)
    print(f"found {len(repo_names)} public FM2 repos")

    for repo_name in repo_names:
        if args.dry_run:
            print(f"[dry-run] would make {repo_name} private and set repo secrets")
            continue
        print(f"[convert] {repo_name} -> private")
        set_repo_private(token, repo_name)
        set_private_repo_secrets(token, repo_name)

    print(f"\ndone: {len(repo_names)} repos processed")


if __name__ == "__main__":
    main()
