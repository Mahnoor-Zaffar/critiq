from __future__ import annotations

import logging

from critiq.integrations.github.client import GitHubClient

logger = logging.getLogger("critiq.push")


async def push_patch(
    client: GitHubClient,
    repo: str,
    pr: dict,
    file_path: str,
    replacement_text: str,
    tested_head_sha: str,
) -> str | None:
    """Push a single verified file change to the PR head ref (AC-5).

    The live ref SHA fetched at push time must equal `tested_head_sha`, the head
    the patch was tested against; on mismatch the push is aborted and returns
    None. Returns the commit sha on success.
    """
    head_ref = pr["head"]["ref"]
    head_is_fork = pr["head"]["repo"]["id"] != pr["base"]["repo"]["id"]
    if head_is_fork:
        logger.info("fork PR %s; skipping push", repo)
        return None
    if await client.branch_protected(repo, head_ref):
        logger.info("branch %s/%s protected; skipping push", repo, head_ref)
        return None

    live_sha = await client.get_ref(repo, head_ref)
    if live_sha != tested_head_sha:
        logger.info(
            "live ref %s != tested head %s; aborting push",
            live_sha,
            tested_head_sha,
        )
        return None

    current_sha = await client.get_file_sha(repo, file_path, head_ref)
    if current_sha is None:
        logger.warning("no current sha for %s/%s; skipping push", repo, file_path)
        return None

    resp = await client.update_file_content(
        repo=repo,
        path=file_path,
        message=f"critiq: apply patch to {file_path}",
        content=replacement_text,
        current_sha=current_sha,
        branch=head_ref,
    )
    commit = resp.get("commit", {})
    sha = commit.get("sha")
    logger.info("pushed %s/%s at %s", repo, file_path, sha)
    return sha
