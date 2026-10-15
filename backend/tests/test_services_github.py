"""GitHub URL parsing.

The host restriction is a security control, not a convenience: this URL is
handed to ``git clone``, so accepting an arbitrary host would make the import
endpoint an SSRF primitive. Those cases are tested as such.
"""

from __future__ import annotations

import pytest

from app.services.github import GitHubRepoRef, InvalidGitHubUrlError, parse_github_url


class TestAcceptedForms:
    @pytest.mark.parametrize(
        "raw",
        [
            "https://github.com/owner/repo",
            "http://github.com/owner/repo",
            "https://www.github.com/owner/repo",
            "github.com/owner/repo",
            "https://github.com/owner/repo.git",
            "https://github.com/owner/repo/",
            "  https://github.com/owner/repo  ",
        ],
    )
    def test_normalises_to_a_canonical_url(self, raw: str) -> None:
        parsed = parse_github_url(raw)

        assert parsed.owner == "owner"
        assert parsed.repo == "repo"
        assert parsed.canonical_url == "https://github.com/owner/repo"

    def test_accepts_ssh_form_and_converts_it(self) -> None:
        parsed = parse_github_url("git@github.com:owner/repo.git")

        assert parsed.canonical_url == "https://github.com/owner/repo"

    def test_accepts_names_with_dots_and_underscores(self) -> None:
        parsed = parse_github_url("https://github.com/my-org/my_repo.js")

        assert parsed.full_name == "my-org/my_repo.js"

    def test_ignores_trailing_path_without_a_ref(self) -> None:
        parsed = parse_github_url("https://github.com/owner/repo/issues/42")

        assert parsed.repo == "repo"


class TestRefHandling:
    def test_recovers_ref_from_a_tree_url(self) -> None:
        parsed = parse_github_url("https://github.com/owner/repo/tree/develop")

        assert parsed.ref == "develop"

    def test_recovers_ref_from_a_deep_blob_url(self) -> None:
        parsed = parse_github_url("https://github.com/owner/repo/blob/main/src/app.ts")

        assert parsed.ref == "main"

    def test_explicit_ref_wins_over_the_url(self) -> None:
        parsed = parse_github_url("https://github.com/owner/repo/tree/develop", ref="v2.0.0")

        assert parsed.ref == "v2.0.0"

    def test_no_ref_when_none_is_present(self) -> None:
        assert parse_github_url("https://github.com/owner/repo").ref is None

    @pytest.mark.parametrize(
        "ref",
        ["--upload-pack=sh", "-oProxyCommand=x", "feature/..", "branch.lock", "with space"],
    )
    def test_rejects_dangerous_refs(self, ref: str) -> None:
        with pytest.raises(InvalidGitHubUrlError):
            parse_github_url("https://github.com/owner/repo", ref=ref)


class TestHostRestriction:
    @pytest.mark.parametrize(
        "raw",
        [
            "https://gitlab.com/owner/repo",
            "https://bitbucket.org/owner/repo",
            "https://github.com.evil.test/owner/repo",
            "https://evilgithub.com/owner/repo",
            "https://raw.githubusercontent.com/owner/repo",
        ],
    )
    def test_rejects_other_hosts(self, raw: str) -> None:
        with pytest.raises(InvalidGitHubUrlError, match="Only github.com"):
            parse_github_url(raw)

    @pytest.mark.parametrize(
        "raw",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://localhost:8000/api/v1/projects",
            "http://127.0.0.1/admin",
            "http://[::1]/",
        ],
    )
    def test_rejects_ssrf_targets(self, raw: str) -> None:
        """Internal addresses must never reach git."""
        with pytest.raises(InvalidGitHubUrlError):
            parse_github_url(raw)

    @pytest.mark.parametrize(
        "raw",
        ["file:///etc/passwd", "ssh://github.com/owner/repo", "ftp://github.com/owner/repo"],
    )
    def test_rejects_non_http_schemes(self, raw: str) -> None:
        with pytest.raises(InvalidGitHubUrlError):
            parse_github_url(raw)

    def test_rejects_embedded_credentials(self) -> None:
        with pytest.raises(InvalidGitHubUrlError, match="credentials"):
            parse_github_url("https://user:token@github.com/owner/repo")

    def test_rejects_a_port(self) -> None:
        with pytest.raises(InvalidGitHubUrlError, match="port"):
            parse_github_url("https://github.com:8080/owner/repo")


class TestMalformedInput:
    @pytest.mark.parametrize("raw", ["", "   ", "https://github.com", "https://github.com/owner"])
    def test_rejects_incomplete_urls(self, raw: str) -> None:
        with pytest.raises(InvalidGitHubUrlError):
            parse_github_url(raw)

    def test_rejects_whitespace_inside_the_url(self) -> None:
        with pytest.raises(InvalidGitHubUrlError, match="whitespace"):
            parse_github_url("https://github.com/owner/re po")

    @pytest.mark.parametrize("raw", ["https://github.com/settings/profile", "github.com/new/repo"])
    def test_rejects_github_site_paths(self, raw: str) -> None:
        with pytest.raises(InvalidGitHubUrlError):
            parse_github_url(raw)

    @pytest.mark.parametrize("owner", ["-leading", "with--double", "a" * 40])
    def test_rejects_invalid_owners(self, owner: str) -> None:
        with pytest.raises(InvalidGitHubUrlError, match="owner"):
            parse_github_url(f"https://github.com/{owner}/repo")


class TestCloneUrls:
    def test_clone_url_has_the_git_suffix(self) -> None:
        assert (
            parse_github_url("https://github.com/owner/repo").clone_url
            == "https://github.com/owner/repo.git"
        )

    def test_authenticated_clone_url_embeds_the_token(self) -> None:
        ref = GitHubRepoRef(owner="owner", repo="repo")

        url = ref.authenticated_clone_url("ghp_example")

        assert url == "https://x-access-token:ghp_example@github.com/owner/repo.git"

    def test_default_project_name_is_the_repo_name(self) -> None:
        assert parse_github_url("https://github.com/owner/my-app").default_project_name == "my-app"
