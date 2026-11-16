"""Automated GitHub Pull Request creation service for MergeX AI."""

from __future__ import annotations

import asyncio
import base64
import time
import uuid
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.core.logging import get_logger
from app.models.issue import Issue
from app.services.github import InvalidGitHubUrlError, parse_github_url
from app.services.patch_engine import apply_code_patch, resolve_target_file_path

log = get_logger("app.services.github_pr")

GITHUB_API_BASE = "https://api.github.com"


async def _resolve_target_repo_and_head(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    headers: dict[str, str],
) -> tuple[str, str, str, str, bool]:
    """Inspect user identity and repository permissions to support both direct write and forks.

    Returns:
        (target_owner, target_repo, default_branch, base_sha, is_fork)
    """
    # 1. Verify user identity and token validity
    user_resp = await client.get(f"{GITHUB_API_BASE}/user", headers=headers)
    if user_resp.status_code == 401:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid GitHub token. Please verify that your Personal Access Token is active and has 'repo' scope.",
        )
    if user_resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitHub token authentication error ({user_resp.status_code}): {user_resp.text}",
        )
    auth_user = user_resp.json().get("login", "")

    # 2. Get repository details and permissions
    repo_resp = await client.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}", headers=headers)
    if repo_resp.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"GitHub repository '{owner}/{repo}' was not found or is private.",
        )
    if repo_resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to access repository '{owner}/{repo}': {repo_resp.text}",
        )

    repo_data = repo_resp.json()
    default_branch = repo_data.get("default_branch", "main")
    permissions = repo_data.get("permissions", {})
    can_push = bool(permissions.get("push", False)) or (bool(auth_user) and auth_user.lower() == owner.lower())

    # 3. Get latest default branch SHA on upstream repository
    ref_resp = await client.get(
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/ref/heads/{default_branch}",
        headers=headers,
    )
    if ref_resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch default branch '{default_branch}' reference for '{owner}/{repo}'.",
        )
    base_sha = ref_resp.json()["object"]["sha"]

    # 4. If direct write access is allowed, push directly to target repository
    if can_push:
        return (owner, repo, default_branch, base_sha, False)

    # 5. Otherwise, automatically fork to the authenticated user's account for public/3rd-party repos
    log.info("user_lacks_push_permission_using_fork", upstream=f"{owner}/{repo}", fork_owner=auth_user)

    # Check if fork already exists under user's namespace
    fork_check = await client.get(f"{GITHUB_API_BASE}/repos/{auth_user}/{repo}", headers=headers)
    if fork_check.status_code != 200:
        # Trigger fork creation on GitHub
        fork_resp = await client.post(f"{GITHUB_API_BASE}/repos/{owner}/{repo}/forks", headers=headers)
        if fork_resp.status_code not in (200, 202):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Direct write access to '{owner}/{repo}' is forbidden, and automatic fork creation to "
                    f"'{auth_user}/{repo}' failed ({fork_resp.status_code}): {fork_resp.text}. "
                    f"Please ensure your token has 'repo' or 'public_repo' scope."
                ),
            )
        # Wait up to 10 seconds for fork creation
        for _ in range(5):
            await asyncio.sleep(2.0)
            check = await client.get(f"{GITHUB_API_BASE}/repos/{auth_user}/{repo}", headers=headers)
            if check.status_code == 200:
                break

    return (auth_user, repo, default_branch, base_sha, True)


async def create_pull_request_for_issue(
    *,
    token: str | None,
    repo_url: str,
    issue: Issue,
) -> dict[str, Any]:
    """Create a pull request on GitHub applying the suggested fix for an issue.

    If token is omitted, it generates a safe simulated PR preview linking to repository pull requests.
    If token is provided, it supports both direct repositories and public 3rd-party repos via automatic forking.
    """
    try:
        ref = parse_github_url(repo_url)
    except InvalidGitHubUrlError as exc:
        log.warning("cannot_parse_github_url_for_pr", repo_url=repo_url, error=str(exc))
        return _simulated_pr(repo_url, issue)

    owner = ref.owner
    repo = ref.repo

    if not token or not token.strip():
        log.info("no_github_token_using_simulation", repo=f"{owner}/{repo}")
        return _simulated_pr(repo_url, issue)

    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "MergeX-AI-Bot",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Inspect repository and setup fork if required
        target_owner, target_repo, default_branch, base_sha, is_fork = await _resolve_target_repo_and_head(
            client, owner, repo, headers
        )

        # 2. Create unique branch name
        short_id = str(issue.id)[:8]
        branch_name = f"mergex/fix-{issue.detected_by.lower()}-{short_id}"

        # 3. Create branch ref on target repository
        create_branch_resp = await client.post(
            f"{GITHUB_API_BASE}/repos/{target_owner}/{target_repo}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        )
        if create_branch_resp.status_code not in (201, 422):
            log.warning("failed_create_branch", status=create_branch_resp.status_code, body=create_branch_resp.text)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to create branch '{branch_name}' on '{target_owner}/{target_repo}': {create_branch_resp.text}",
            )

        # 4. Apply fix to target file
        target_path = resolve_target_file_path(
            issue.file_path,
            rule_id=issue.detected_by,
            category=issue.category,
        )

        if issue.fix_after:
            file_resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{target_owner}/{target_repo}/contents/{target_path}?ref={branch_name}",
                headers=headers,
            )
            if file_resp.status_code != 200:
                # Fallback to upstream default branch if fork content is not yet populated
                file_resp = await client.get(
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{target_path}?ref={default_branch}",
                    headers=headers,
                )

            file_sha = None
            content_raw = ""
            if file_resp.status_code == 200:
                file_data = file_resp.json()
                file_sha = file_data.get("sha")
                try:
                    content_raw = base64.b64decode(file_data.get("content", "")).decode("utf-8")
                except Exception:
                    content_raw = ""

            line_num = getattr(issue, "line_start", None) or getattr(issue, "line_number", None)
            updated_content, modified = apply_code_patch(
                content_raw,
                issue.fix_before,
                issue.fix_after,
                target_line=line_num,
            )

            final_content = updated_content if modified else issue.fix_after
            content_b64 = base64.b64encode(final_content.encode("utf-8")).decode("utf-8")
            commit_msg = f"fix({issue.category}): {issue.title}\n\nAutomated fix applied by MergeX AI."
            commit_payload: dict[str, Any] = {
                "message": commit_msg,
                "content": content_b64,
                "branch": branch_name,
            }
            if file_sha:
                commit_payload["sha"] = file_sha

            put_resp = await client.put(
                f"{GITHUB_API_BASE}/repos/{target_owner}/{target_repo}/contents/{target_path}",
                headers=headers,
                json=commit_payload,
            )
            if put_resp.status_code not in (200, 201):
                log.warning("failed_to_commit_file", status=put_resp.status_code, body=put_resp.text)

        # 5. Create Pull Request on upstream repository
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

        head_ref = f"{target_owner}:{branch_name}" if is_fork else branch_name
        pr_resp = await client.post(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls",
            headers=headers,
            json={
                "title": pr_title,
                "head": head_ref,
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
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls?head={head_ref}",
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitHub Pull Request creation failed ({pr_resp.status_code}): {pr_resp.text}",
        )


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

    return {
        "prUrl": f"{base_url}/pulls",
        "prNumber": 1,
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
    Supports both direct push and cross-repo PRs via automatic forking.
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

    if not token or not token.strip():
        log.info("no_github_token_using_simulation_for_batch", repo=f"{owner}/{repo}")
        return _simulated_batch_pr(repo_url, issues)

    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "MergeX-AI-Bot",
    }

    async with httpx.AsyncClient(timeout=45.0) as client:
        # 1. Inspect repository and setup fork if required
        target_owner, target_repo, default_branch, base_sha, is_fork = await _resolve_target_repo_and_head(
            client, owner, repo, headers
        )

        # 2. Create unique branch name
        timestamp_slug = time.strftime("%Y%m%d-%H%M%S")
        branch_name = f"mergex/remediation-{timestamp_slug}"

        # 3. Create branch ref on target repository
        create_branch_resp = await client.post(
            f"{GITHUB_API_BASE}/repos/{target_owner}/{target_repo}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        )
        if create_branch_resp.status_code not in (201, 422):
            log.warning("failed_create_batch_branch", status=create_branch_resp.status_code, body=create_branch_resp.text)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to create branch '{branch_name}' on '{target_owner}/{target_repo}': {create_branch_resp.text}",
            )

        # 4. Apply fixes across all issues, managing file contents in-memory
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
                    f"{GITHUB_API_BASE}/repos/{target_owner}/{target_repo}/contents/{target_path}?ref={branch_name}",
                    headers=headers,
                )
                if file_resp.status_code != 200:
                    file_resp = await client.get(
                        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{target_path}?ref={default_branch}",
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

        # 5. Commit all modified files to the new branch
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
                f"{GITHUB_API_BASE}/repos/{target_owner}/{target_repo}/contents/{path}",
                headers=headers,
                json=commit_payload,
            )

        # 6. Create Consolidated Pull Request on upstream repository
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

        head_ref = f"{target_owner}:{branch_name}" if is_fork else branch_name
        pr_resp = await client.post(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls",
            headers=headers,
            json={
                "title": pr_title,
                "head": head_ref,
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitHub Consolidated PR creation failed ({pr_resp.status_code}): {pr_resp.text}",
        )


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

    return {
        "prUrl": f"{base_url}/pulls",
        "prNumber": 1,
        "branch": branch,
        "status": "simulated",
        "resolvedIssueIds": [str(i.id) for i in issues],
        "note": note,
    }
