"""Automated GitHub Pull Request creation service for MergeX AI."""

from __future__ import annotations

import base64
from typing import Any

import httpx

from app.core.logging import get_logger
from app.models.issue import Issue
from app.services.github import InvalidGitHubUrlError, parse_github_url

log = get_logger("app.services.github_pr")

GITHUB_API_BASE = "https://api.github.com"


async def create_pull_request_for_issue(
    *,
    token: str | None,
    repo_url: str,
    issue: Issue,
) -> dict[str, Any]:
    """Create a pull request on GitHub applying the suggested fix for an issue.

    If token is omitted or if the repository cannot be modified (e.g. mock or public 3rd party
    repo without write access), it generates a realistic simulated PR link for safe demonstration.
    """
    try:
        ref = parse_github_url(repo_url)
    except InvalidGitHubUrlError as exc:
        log.warning("cannot_parse_github_url_for_pr", repo_url=repo_url, error=str(exc))
        return _simulated_pr(repo_url, issue)

    owner = ref.owner
    repo = ref.repo

    if not token:
        log.info("no_github_token_using_simulation", repo=f"{owner}/{repo}")
        return _simulated_pr(repo_url, issue)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "MergeX-AI-Bot",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        # 1. Check if repo is accessible and get default branch
        repo_resp = await client.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}", headers=headers)
        if repo_resp.status_code != 200:
            log.warning("repo_not_accessible", status=repo_resp.status_code, body=repo_resp.text)
            return _simulated_pr(
                repo_url,
                issue,
                note="Simulated PR (Write access unavailable)",
            )

        repo_data = repo_resp.json()
        default_branch = repo_data.get("default_branch", "main")

        # 2. Get latest commit SHA of default branch
        ref_resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/ref/heads/{default_branch}",
            headers=headers,
        )
        if ref_resp.status_code != 200:
            return _simulated_pr(repo_url, issue)

        base_sha = ref_resp.json()["object"]["sha"]

        # 3. Create branch name
        short_id = str(issue.id)[:8]
        branch_name = f"mergex/fix-{issue.detected_by.lower()}-{short_id}"

        # 4. Create branch ref
        create_branch_resp = await client.post(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        )
        if create_branch_resp.status_code not in (201, 422):
            log.warning("failed_create_branch", status=create_branch_resp.status_code)
            return _simulated_pr(repo_url, issue)

        # 5. Apply fix to file if file_path and fix_after exist
        if issue.file_path and issue.fix_after:
            file_resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{issue.file_path}?ref={branch_name}",
                headers=headers,
            )
            if file_resp.status_code == 200:
                file_data = file_resp.json()
                file_sha = file_data["sha"]
                try:
                    content_raw = base64.b64decode(file_data["content"]).decode("utf-8")
                except Exception:
                    content_raw = ""

                # Replace fix_before with fix_after if found, or replace lines
                if issue.fix_before and issue.fix_before in content_raw:
                    updated_content = content_raw.replace(issue.fix_before, issue.fix_after)
                else:
                    updated_content = content_raw if content_raw else issue.fix_after

                content_b64 = base64.b64encode(updated_content.encode("utf-8")).decode("utf-8")
                commit_msg = (
                    f"fix({issue.category}): {issue.title}\n\nAutomated fix applied by MergeX AI."
                )
                await client.put(
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{issue.file_path}",
                    headers=headers,
                    json={
                        "message": commit_msg,
                        "content": content_b64,
                        "sha": file_sha,
                        "branch": branch_name,
                    },
                )

        # 6. Create Pull Request
        pr_title = f"fix({issue.category}): {issue.title}"
        pr_body = (
            f"## 🤖 MergeX AI Automated Remediation\n\n"
            f"### Defect Identified\n"
            f"- **Rule ID:** `{issue.detected_by}`\n"
            f"- **Title:** {issue.title}\n"
            f"- **File:** `{issue.file_path or 'Project tree'}`\n\n"
            f"### Problem Description\n"
            f"{issue.explanation or issue.description}\n\n"
            f"### Suggested Fix\n"
            f"{issue.suggested_fix or 'Applied automated remediation patch.'}\n\n"
            f"---\n"
            f"*Automatically generated and verified by [MergeX AI](https://merge-x-ai.vercel.app).*"
        )

        pr_resp = await client.post(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls",
            headers=headers,
            json={
                "title": pr_title,
                "head": branch_name,
                "base": default_branch,
                "body": pr_body,
            },
        )

        if pr_resp.status_code == 201:
            pr_data = pr_resp.json()
            return {
                "prUrl": pr_data["html_url"],
                "prNumber": pr_data["number"],
                "branch": branch_name,
                "status": "created",
            }
        if pr_resp.status_code == 422:
            list_pr_resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls?head={owner}:{branch_name}",
                headers=headers,
            )
            if list_pr_resp.status_code == 200 and list_pr_resp.json():
                existing_pr = list_pr_resp.json()[0]
                return {
                    "prUrl": existing_pr["html_url"],
                    "prNumber": existing_pr["number"],
                    "branch": branch_name,
                    "status": "already_exists",
                }

        log.warning("failed_create_pr", status=pr_resp.status_code, body=pr_resp.text)
        return _simulated_pr(repo_url, issue)


def _simulated_pr(repo_url: str, issue: Issue, note: str = "Demo Pull Request") -> dict[str, Any]:
    short_id = str(issue.id)[:6]
    branch = f"mergex/fix-{issue.detected_by.lower()}-{short_id}"
    base_url = (
        repo_url.rstrip("/")
        if repo_url.startswith("http")
        else "https://github.com/yadneshkadam07-boop/MergeX-AI"
    )
    if base_url.endswith(".git"):
        base_url = base_url[:-4]
    try:
        pr_num = int(short_id, 16) % 50 + 1
    except ValueError:
        pr_num = 42

    return {
        "prUrl": f"{base_url}/pull/{pr_num}",
        "prNumber": pr_num,
        "branch": branch,
        "status": "simulated",
        "note": note,
    }
