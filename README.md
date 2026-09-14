# iZen Shared Config

This repository contains shared configuration for the GitHub → Moodle integration.
Note: Course ID 21 is AI-ML Toolkit: Python & Data Science FOundations and Course ID 19 is for the Machine Learning Engineer course.

Files:
- github_moodle_map.csv: maps GitHub usernames to Moodle student IDs
- courses.json: course IDs in Moodle
- assignments.json: assignment → Moodle activity IDs
- grading_config.json: optional grading settings
- provision_repos.py / roster.csv: student repo provisioning (see below)

## Repo provisioning (replaces GitHub Classroom, retired 2026-08-28)

GitHub Classroom used to create a student's assignment repo when they accepted
an invite. `provision_repos.py` replaces that step with a direct call to the
GitHub REST API's "generate from template" endpoint — no Classroom or
Classroom 50 dependency, works on the org's Free tier.

To provision repos for new students, add a row per (student, assignment) to
`roster.csv`:

```
github_username,assignment_code
someusername,FM2
```

Assignment codes: `FM2` (Python), `FM3` (NumPy), `FM4` (Pandas), `FM7`
(Feature Engineering). Pushing a change to `roster.csv` on `main` triggers the
`Provision student repos` workflow automatically; it skips any repo that
already exists, so it's safe to leave old rows in place.

The workflow needs a repo secret `PROVISION_PAT`: a fine-grained PAT scoped to
this org with Administration (write) and Contents (write) at the repository
level, plus repository-level Secrets (read/write).

### Why private repos need special handling

This org is on GitHub's **Free** plan. On Free, an org-level Actions secret
scoped to "All repositories" (like `MOODLE_URL` and `MOODLE_TOKEN`) is only
ever passed to **public** repos — private repos never receive it, no matter
how they were created. This isn't new or caused by the Classroom migration:
it's been silently breaking Moodle sync for every private assignment (NumPy,
Pandas, Feature Engineering) since at least mid-2026. Only the public FM2
(Python) repos have ever synced correctly.

Since `izen-shared-config` is itself public, its own workflow *can* read
`secrets.MOODLE_URL` / `secrets.MOODLE_TOKEN` fine. `provision_repos.py` uses
that to push copies of both onto every new **private** repo as repo-level
secrets (which work regardless of plan), right after creating it. This means
the workflow also needs `MOODLE_URL` and `MOODLE_TOKEN` in its own `env:` —
already wired up in `provision-repos.yml`, sourced from the same org secrets.

Existing private student repos created before this fix has the same problem
and need a one-time backfill — see `backfill_repo_secrets.py`.

To run manually instead:

```
PROVISION_PAT=<token> MOODLE_URL=<value> MOODLE_TOKEN=<value> python provision_repos.py --roster roster.csv --dry-run
```

Drop `--dry-run` to actually create repos, add collaborators, and set repo
secrets on private repos.

## Self-service repo requests (students)

Give students this link:

**https://github.com/iZen-AI-Academy/izen-shared-config/issues/new?template=request-repo.yml**

They pick their assignment from a dropdown and submit. Because they're
already logged into GitHub, their username is captured automatically from
who actually opened the issue — not a text field they type into, so there's
no way to request a repo under someone else's name. A workflow
(`provision-from-issue.yml`) picks up the request, runs the same
provisioning logic as `provision_repos.py` for that one student, comments
the result on the issue (the new repo's link, or a clear error), and closes
it either way.

Only GitHub usernames already present in `github_moodle_map.csv` can
request a repo this way — since this repo is public, anyone with a GitHub
account can technically open the issue, and that roster check is the guard
against a stranger getting a repo (and a copy of the Moodle secrets) created
for them.
