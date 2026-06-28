# ==================== core/git_manager.py ====================
import os
from github import Github, GithubException

def upload_file_to_github(token: str, repo_full: str, remote_path: str, file_content: bytes, commit_message: str = "Auto-upload"):
    """
    上传单个文件到 GitHub 仓库的指定路径。
    """
    g = Github(token)
    repo = g.get_repo(repo_full)
    try:
        contents = repo.get_contents(remote_path)
        repo.update_file(remote_path, commit_message, file_content, contents.sha)
        return True, f"更新文件 {remote_path}"
    except GithubException as e:
        if e.status == 404:
            repo.create_file(remote_path, commit_message, file_content)
            return True, f"创建文件 {remote_path}"
        else:
            raise

def download_file_from_github(token: str, repo_full: str, remote_path: str) -> bytes:
    """
    从 GitHub 仓库下载指定文件的内容。
    """
    g = Github(token)
    repo = g.get_repo(repo_full)
    try:
        contents = repo.get_contents(remote_path)
        return contents.decoded_content
    except GithubException as e:
        raise RuntimeError(f"下载失败: {e.status} - {e.data.get('message','')}")