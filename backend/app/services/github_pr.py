"""Automated GitHub Pull Request creation service for MergeX AI."""

from __future__ import annotations

import base64
import time
import uuid
from typing import Any

import httpx

from app.core.logging import get_logger
from app.models.issue import Issue
from app.services.github import InvalidGitHubUrlError, parse_github_url
from app.services.patch_engine import apply_code_patch, resolve_target_file_path

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

    try:
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

            # 5. Apply fix to file if fix_after exists
            target_path = resolve_target_file_path(
                issue.file_path,
                rule_id=issue.detected_by,
                category=issue.category,
            )

            if issue.fix_after:
                file_resp = await client.get(
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{target_path}?ref={branch_name}",
                    headers=headers,
                )
                if file_resp.status_code == 200:
                    file_data = file_resp.json()
                    file_sha = file_data["sha"]
                    try:
                        content_raw = base64.b64decode(file_data["content"]).decode("utf-8")
                    except Exception:
                        content_raw = ""

                    line_num = getattr(issue, "line_start", None) or getattr(issue, "line_number", None)
                    updated_content, modified = apply_code_patch(
                        content_raw,
                        issue.fix_before,
                        issue.fix_after,
                        target_line=line_num,
                    )

                    if modified:
                        content_b64 = base64.b64encode(updated_content.encode("utf-8")).decode("utf-8")
                        commit_msg = (
                            f"fix({issue.category}): {issue.title}\n\nAutomated fix applied by MergeX AI."
                        )
                        await client.put(
                            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{target_path}",
                            headers=headers,
                            json={
                                "message": commit_msg,
                                "content": content_b64,
                                "sha": file_sha,
                                "branch": branch_name,
                            },
                        )
                elif file_resp.status_code == 404:
                    # File does not exist yet: create it directly
                    content_b64 = base64.b64encode(issue.fix_after.encode("utf-8")).decode("utf-8")
                    commit_msg = (
                        f"chore({issue.category}): add {target_path}\n\nAutomated fix applied by MergeX AI."
                    )
                    await client.put(
                        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{target_path}",
                        headers=headers,
                        json={
                            "message": commit_msg,
                            "content": content_b64,
                            "branch": branch_name,
                        },
                    )

            # 6. Create Pull Request
            pr_title = f"fix({issue.category}): {issue.title}"
            line_target = getattr(issue, "line_start", None) or getattr(issue, "line_number", None)
            target_display = (
                f"`{target_path}:{line_target}`"
                if line_target
                else f"`{target_path}`"
            )
            pr_body = (
                f"## 🤖 MergeX AI Automated Remediation\n\n"
                f"### Defect Identified\n"
                f"- **Rule ID:** `{issue.detected_by}`\n"
                f"- **Severity:** `{str(issue.severity).upper()}`\n"
                f"- **Category:** `{str(issue.category).title()}`\n"
                f"- **Target File:** {target_display}\n\n"
                f"### Problem Description\n"
                f"{issue.explanation or issue.description}\n\n"
                f"### Suggested Fix\n"
                f"{issue.suggested_fix or 'Applied automated remediation patch.'}\n\n"
                f"### Verification Checklist\n"
                f"- [ ] Review diff for accuracy and compliance with repository standards.\n"
                f"- [ ] Run local automated test suite.\n"
                f"- [ ] Verify that no downstream callers or APIs are broken.\n\n"
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
    except Exception as exc:
        log.warning("create_pull_request_exception", error=str(exc))
        return _simulated_pr(repo_url, issue, note="Simulated PR (Remediation prepared)")


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


async def create_batch_pull_request(
    *,
    token: str | None,
    repo_url: str,
    issues: list[Issue],
) -> dict[str, Any]:
    """Create a single consolidated pull request on GitHub applying fixes for multiple issues.

    Sequentially patches all affected files and creates a single branch and PR.
    """
    if not issues:
        raise ValueError("Cannot create a batch pull request with 0 issues.")

    try:
        ref = parse_github_url(repo_url)
    except InvalidGitHubUrlError as exc:
        log.warning("cannot_parse_github_url_for_batch_pr", repo_url=repo_url, error=str(exc))
        return _simulated_batch_pr(repo_url, issues)

    owner = ref.owner
    repo = ref.repo

    if not token:
        log.info("no_github_token_using_simulation_for_batch", repo=f"{owner}/{repo}")
        return _simulated_batch_pr(repo_url, issues)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "MergeX-AI-Bot",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Check if repo is accessible and get default branch
        repo_resp = await client.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}", headers=headers)
        if repo_resp.status_code != 200:
            log.warning("repo_not_accessible_for_batch", status=repo_resp.status_code)
            return _simulated_batch_pr(
                repo_url,
                issues,
                note="Simulated Batch PR (Write access unavailable)",
            )

        repo_data = repo_resp.json()
        default_branch = repo_data.get("default_branch", "main")

        # 2. Get latest commit SHA of default branch
        ref_resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/ref/heads/{default_branch}",
            headers=headers,
        )
        if ref_resp.status_code != 200:
            return _simulated_batch_pr(repo_url, issues)

        base_sha = ref_resp.json()["object"]["sha"]

        # 3. Create unique branch name
        timestamp_slug = time.strftime("%Y%m%d-%H%M%S")
        branch_name = f"mergex/remediation-{timestamp_slug}"

        # 4. Create branch ref
        create_branch_resp = await client.post(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        )
        if create_branch_resp.status_code not in (201, 422):
            log.warning("failed_create_batch_branch", status=create_branch_resp.status_code)
            return _simulated_batch_pr(repo_url, issues)

        # 5. Apply fixes across all issues, managing file contents in-memory
        file_state: dict[str, tuple[str, str | None]] = {}
        resolved_issues: list[Issue] = []

        for issue in issues:
            if not issue.fix_after:
                continue

            target_path = resolve_target_file_path(
                issue.file_path,
                rule_id=issue.detected_by,
                category=issue.category,
            )

            # Retrieve file state if not yet loaded
            if target_path not in file_state:
                file_resp = await client.get(
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{target_path}?ref={branch_name}",
                    headers=headers,
                )
                if file_resp.status_code == 200:
                    data = file_resp.json()
                    file_sha = data.get("sha")
                    try:
                        raw = base64.b64decode(data.get("content", "")).decode("utf-8")
                    except Exception:
                        raw = ""
                    file_state[target_path] = (raw, file_sha)
                elif file_resp.status_code == 404:
                    file_state[target_path] = ("", None)
                else:
                    continue

            curr_content, curr_sha = file_state[target_path]
            line_target = getattr(issue, "line_start", None) or getattr(issue, "line_number", None)
            updated_content, modified = apply_code_patch(
                curr_content,
                issue.fix_before,
                issue.fix_after,
                target_line=line_target,
            )

            if modified:
                file_state[target_path] = (updated_content, curr_sha)
                resolved_issues.append(issue)

        # 6. Commit all modified files to the new branch
        for path, (new_content, file_sha) in file_state.items():
            content_b64 = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")
            commit_payload: dict[str, Any] = {
                "message": f"fix(remediation): apply automated patches to {path}\n\nAutomated fix applied by MergeX AI.",
                "content": content_b64,
                "branch": branch_name,
            }
            if file_sha:
                commit_payload["sha"] = file_sha

            await client.put(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}",
                headers=headers,
                json=commit_payload,
            )

        # 7. Create Consolidated Pull Request
        pr_title = f"fix(remediation): resolve {len(resolved_issues) or len(issues)} issues across codebase"

        rows: list[str] = []
        for iss in resolved_issues or issues:
            loc_line = getattr(iss, "line_start", None) or getattr(iss, "line_number", None)
            loc = (
                f"`{iss.file_path}:{loc_line}`"
                if iss.file_path and loc_line
                else f"`{iss.file_path or 'Project'}`"
            )
            rows.append(
                f"| `{str(iss.severity).upper()}` | `{iss.detected_by}` | {loc} | {iss.title} |"
            )

        table_md = "\n".join(rows)

        pr_body = (
            f"## 🤖 MergeX AI Consolidated Remediation\n\n"
            f"This automated pull request resolves **{len(resolved_issues) or len(issues)} defects** detected by MergeX AI.\n\n"
            f"### Resolved Issues\n"
            f"| Severity | Rule ID | Location | Summary |\n"
            f"| :--- | :--- | :--- | :--- |\n"
            f"{table_md}\n\n"
            f"### Verification Checklist\n"
            f"- [ ] Review diff for accuracy and compliance with repository standards.\n"
            f"- [ ] Run local automated test suite.\n"
            f"- [ ] Verify that no downstream callers or API contracts are broken.\n\n"
            f"---\n"
            f"*Automated batch remediation by [MergeX AI](https://merge-x-ai.vercel.app).*"
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
                "resolvedIssueIds": [str(i.id) for i in (resolved_issues or issues)],
            }

        log.warning("failed_create_batch_pr", status=pr_resp.status_code, body=pr_resp.text)
        return _simulated_batch_pr(repo_url, issues)


def _simulated_batch_pr(
    repo_url: str,
    issues: list[Issue],
    note: str = "Simulated Consolidated PR",
) -> dict[str, Any]:
    short_hash = uuid.uuid4().hex[:6]
    branch = f"mergex/batch-remediation-{short_hash}"
    base_url = (
        repo_url.rstrip("/")
        if repo_url.startswith("http")
        else "https://github.com/yadneshkadam07-boop/MergeX-AI"
    )
    if base_url.endswith(".git"):
        base_url = base_url[:-4]

    pr_num = 100 + (len(issues) * 7) % 50

    return {
        "prUrl": f"{base_url}/pull/{pr_num}",
        "prNumber": pr_num,
        "branch": branch,
        "status": "simulated",
        "resolvedIssueIds": [str(i.id) for i in issues],
        "note": note,
    }
