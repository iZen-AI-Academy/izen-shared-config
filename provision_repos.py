#!/usr/bin/env python3
"""Create per-student assignment repos from templates in the iZen-AI-Academy org.

Replaces the repo-creation step GitHub Classroom used to handle (retired
2026-08-28). Reads a roster CSV of (github_username, assignment_code) pairs,
generates a repo from the matching template for any pair that doesn't already
have one, and adds the student as a collaborator.

Usage:
    python provision_repos.py --roster roster.csv [--dry-run]

Requires env var PROVISION_PAT: a fine-grained PAT scoped to the
iZen-AI-Academy org with Administration (write) and Contents (write) at the
repository level, plus repository-level Secrets (read/write).

Also requires MOODLE_URL and MOODLE_TOKEN env vars (the same values as the
org's Actions secrets of the same name) for any private repo being created.
The org is on GitHub's Free plan, which only exposes org-level Actions
secrets to *public* repos -- private repos never see them. Since this script
runs from izen-shared-config (a public repo), it can read the org secrets
fine via its own workflow's env, then pushes copies of them onto each new
*private* repo as repo-level secrets, which work regardless of plan.
"""
import argparse
import csv
import os
import sys
import time

import nacl.encoding
import nacl.public
import requests
from github import Auth, Github, GithubException

ORG = "iZen-AI-Academy"

# assignment_code -> template repo name, resulting repo prefix, and visibility.
# Repo prefixes intentionally match the pre-existing student repos so that
# downstream grading/Moodle-sync automation keeps matching by name.
ASSIGNMENT_CONFIG = {
    "FM2": {"template": "fm2_python_template", "prefix": "fm3-python-programming", "private": True},
    "FM3": {"template": "fm3_numpy_template", "prefix": "fm4-numpy", "private": True},
    "FM4": {"template": "fm4_pandas_template", "prefix": "fm4-pandas", "private": True},
    "FM7": {"template": "fm7_feature_engineering_template", "prefix": "fm8-feature-engineering", "private": True},
}

COLLABORATOR_PERMISSION = "push"

# Secrets each private repo's grading workflow needs (see module docstring for
# why these have to be pushed as repo-level secrets on Free tier). Values are
# read from this script's own environment, not hardcoded.
REQUIRED_SECRETS_FOR_PRIVATE_REPOS = ["MOODLE_URL", "MOODLE_TOKEN"]


def repo_name_for(username: str, assignment_code: str) -> str:
    return f"{ASSIGNMENT_CONFIG[assignment_code]['prefix']}-{username}"


def repo_exists(gh: Github, name: str) -> bool:
    try:
        gh.get_repo(f"{ORG}/{name}")
        return True
    except GithubException as e:
        if e.status == 404:
            return False
        raise


def _api_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def generate_from_template(token: str, template_name: str, new_name: str, private: bool) -> dict:
    resp = requests.post(
        f"https://api.github.com/repos/{ORG}/{template_name}/generate",
        headers=_api_headers(token),
        json={"owner": ORG, "name": new_name, "private": private, "include_all_branches": False},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def set_repo_private(token: str, repo_name: str) -> None:
    resp = requests.patch(
        f"https://api.github.com/repos/{ORG}/{repo_name}",
        headers=_api_headers(token),
        json={"private": True},
        timeout=30,
    )
    resp.raise_for_status()


def get_repo_public_key(token: str, repo_name: str) -> tuple[str, str]:
    resp = requests.get(
        f"https://api.github.com/repos/{ORG}/{repo_name}/actions/secrets/public-key",
        headers=_api_headers(token),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["key_id"], data["key"]


def set_repo_secret(token: str, repo_name: str, secret_name: str, secret_value: str) -> None:
    """Create/update a repository-level Actions secret.

    Repo-level secrets work regardless of the org's billing plan, unlike
    org-level secrets scoped to "All repositories" (see module docstring).
    """
    key_id, public_key = get_repo_public_key(token, repo_name)
    sealed_box = nacl.public.SealedBox(nacl.public.PublicKey(public_key.encode(), nacl.encoding.Base64Encoder()))
    encrypted = sealed_box.encrypt(secret_value.encode())
    encrypted_b64 = nacl.encoding.Base64Encoder.encode(encrypted).decode()

    resp = requests.put(
        f"https://api.github.com/repos/{ORG}/{repo_name}/actions/secrets/{secret_name}",
        headers=_api_headers(token),
        json={"encrypted_value": encrypted_b64, "key_id": key_id},
        timeout=30,
    )
    resp.raise_for_status()


def set_private_repo_secrets(token: str, repo_name: str) -> None:
    """Push MOODLE_URL/MOODLE_TOKEN onto a private repo as repo-level secrets.

    Best-effort per secret: a missing env var or API failure is reported but
    doesn't fail provisioning, since the repo + collaborator invite already
    succeeded and are the higher-priority outcome.
    """
    for name in REQUIRED_SECRETS_FOR_PRIVATE_REPOS:
        value = os.environ.get(name)
        if not value:
            print(f"[warn] env var {name} not set, skipping repo secret on {repo_name}", file=sys.stderr)
            continue
        try:
            set_repo_secret(token, repo_name, name, value)
            print(f"[create] set repo secret {name} on {repo_name}")
        except requests.HTTPError as e:
            print(f"[warn] could not set repo secret {name} on {repo_name}: {e}", file=sys.stderr)


def add_collaborator(gh: Github, repo_name: str, username: str) -> None:
    repo = gh.get_repo(f"{ORG}/{repo_name}")
    repo.add_to_collaborators(username, permission=COLLABORATOR_PERMISSION)


def load_roster(path: str) -> list[tuple[str, str]]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):
            username = (row.get("github_username") or "").strip()
            code = (row.get("assignment_code") or "").strip().upper()
            if not username or not code:
                continue
            if code not in ASSIGNMENT_CONFIG:
                print(f"roster.csv:{i}: unknown assignment_code '{code}', skipping", file=sys.stderr)
                continue
            rows.append((username, code))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", default="roster.csv")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("PROVISION_PAT")
    if not token:
        sys.exit("PROVISION_PAT env var is required")

    gh = Github(auth=Auth.Token(token))
    roster = load_roster(args.roster)
    if not roster:
        print("roster is empty, nothing to do")
        return

    created, skipped, failed = 0, 0, 0
    for username, code in roster:
        cfg = ASSIGNMENT_CONFIG[code]
        repo_name = repo_name_for(username, code)

        if repo_exists(gh, repo_name):
            print(f"[skip] {repo_name} already exists")
            skipped += 1
            continue

        if args.dry_run:
            secret_note = (f", and set repo secrets: {', '.join(REQUIRED_SECRETS_FOR_PRIVATE_REPOS)}"
                            if cfg["private"] else "")
            print(f"[dry-run] would create {ORG}/{repo_name} from {cfg['template']} "
                  f"(private={cfg['private']}), add {username} as collaborator{secret_note}")
            continue

        try:
            print(f"[create] {repo_name} from {cfg['template']}")
            generate_from_template(token, cfg["template"], repo_name, cfg["private"])
            time.sleep(2)  # let GitHub finish provisioning before we touch collaborators/secrets
            add_collaborator(gh, repo_name, username)
            print(f"[create] added {username} as collaborator on {repo_name}")
            if cfg["private"]:
                set_private_repo_secrets(token, repo_name)
            created += 1
        except (requests.HTTPError, GithubException) as e:
            print(f"[error] {repo_name}: {e}", file=sys.stderr)
            failed += 1

    print(f"\ndone: {created} created, {skipped} skipped, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
