#!/usr/bin/env python3
"""Provision a single student repo from a GitHub Issue Form request.

Invoked by .github/workflows/provision-from-issue.yml when a student
submits the "Request my assignment repo" issue template. Reads
GITHUB_USERNAME (the issue's actual author, not user-typed) and
ASSIGNMENT_CODE (parsed from the form) from the environment, then
provisions the repo using the same logic as provision_repos.py.

Prints a single markdown message on stdout meant to be posted back as
a comment on the issue -- this is the only output the workflow uses to
report success or failure to the student.
"""
import csv
import os
import sys
import time

from github import Auth, Github, GithubException

from provision_repos import (
    ASSIGNMENT_CONFIG,
    ORG,
    add_collaborator,
    generate_from_template,
    repo_exists,
    repo_name_for,
    set_private_repo_secrets,
)

MOODLE_MAP_PATH = "github_moodle_map.csv"


def is_known_student(username: str) -> bool:
    """Only provision repos for GitHub users already in the Moodle roster.

    This repo-request flow is reachable by anyone with a GitHub account
    (it's a public repo), so this is the one guard against a stranger
    getting a private repo -- and a copy of the Moodle sync secrets --
    created for them.
    """
    username = username.strip().lower()
    with open(MOODLE_MAP_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return any(row.get("github_username", "").strip().lower() == username for row in reader)


def main():
    token = os.environ.get("PROVISION_PAT")
    if not token:
        print("Internal error: this repo isn't configured correctly (missing PROVISION_PAT). "
              "Please let a staff member know.")
        sys.exit(1)

    username = os.environ.get("GITHUB_USERNAME", "").strip()
    code = os.environ.get("ASSIGNMENT_CODE", "").strip().upper()

    if not username:
        print("Couldn't determine your GitHub username from this issue. Please try again.")
        sys.exit(1)

    if code not in ASSIGNMENT_CONFIG:
        valid = ", ".join(sorted(ASSIGNMENT_CONFIG))
        print(f"'{code}' isn't a recognized assignment code (parsed from the form). "
              f"Valid codes: {valid}. Please open a new request and pick a listed option.")
        sys.exit(1)

    if not is_known_student(username):
        print(f"GitHub user `{username}` isn't in our roster yet, so I can't create a repo automatically. "
              f"Please contact a staff member to get enrolled first.")
        sys.exit(1)

    cfg = ASSIGNMENT_CONFIG[code]
    repo_name = repo_name_for(username, code)
    gh = Github(auth=Auth.Token(token))

    if repo_exists(gh, repo_name):
        print(f"You already have a repo for this assignment: https://github.com/{ORG}/{repo_name}")
        return

    try:
        print(f"[create] {repo_name} from {cfg['template']}", file=sys.stderr)
        generate_from_template(token, cfg["template"], repo_name, cfg["private"])
        time.sleep(2)
        add_collaborator(gh, repo_name, username)
        if cfg["private"]:
            set_private_repo_secrets(token, repo_name)
    except GithubException as e:
        print(f"Something went wrong creating your repo: {e}\n\n"
              f"A staff member will need to look into this.")
        sys.exit(1)

    print(f"Your repo is ready: **https://github.com/{ORG}/{repo_name}**\n\n"
          f"Check your GitHub notifications for a collaborator invite if you don't see the repo yet.")


if __name__ == "__main__":
    main()
