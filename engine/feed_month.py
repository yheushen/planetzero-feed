"""The feed branch starts fresh on the 1st of each month (session 7bc, part 86; the owner's yes of 16 Oct 2026).

    python3 engine/feed_month.py _feed      # in the feed Action, after the build, before publishing

Every hour adds a commit of about 8 MB to the public feed repo's `feed` branch, about 250 MB a month. When the branch's first commit is
from an earlier month (Malaysia and Singapore time), its history is dropped: 1 orphan commit holds every file as it is now, the
month's `history/` included, and the Action pushes it in place of the branch (with a lease, so a newer push is never overwritten).
GitHub Pages serves the files, which do not change. Prints `fresh=yes` or `fresh=no` for the Action.
"""
import datetime as dt
import subprocess
import sys

TZ8 = dt.timezone(dt.timedelta(hours=8))


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def month_of(t):
    return t.astimezone(TZ8).strftime("%Y-%m")


def fresh_start(repo, now=None):
    """True when the branch was started fresh: its first commit is from an earlier month than `now`. Local only; the Action pushes."""
    now = now or dt.datetime.now(TZ8)
    roots = git(repo, "rev-list", "--max-parents=0", "HEAD").split()
    first = min(dt.datetime.fromisoformat(git(repo, "show", "-s", "--format=%cI", r)) for r in roots)
    if month_of(first) == month_of(now):
        return False
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    git(repo, "checkout", "-q", "--orphan", "_fresh")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"feed: a fresh start for {now.astimezone(TZ8):%B %Y} (earlier commits dropped; every file kept, history/ included)")
    if branch not in ("HEAD", "_fresh"):
        git(repo, "branch", "-M", "_fresh", branch)
    return True


if __name__ == "__main__":
    print(f"fresh={'yes' if fresh_start(sys.argv[1] if len(sys.argv) > 1 else '.') else 'no'}")
