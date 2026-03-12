"""
infrastructure/git_manager.py — Git Sync & Deployment Trigger
"""
import subprocess
import os
from infrastructure.logger import get_logger

logger = get_logger("GitManager")

def automatic_sync():
    """
    Checks for local changes, commits them with a standard message, and pushes to origin.
    Returns True if sync was performed or unnecessary, False on failure.
    """
    try:
        # 1. PORCELAIN check to see if there are changes
        status_proc = subprocess.run(
            ["git", "status", "--porcelain"], 
            capture_output=True, text=True, check=True
        )
        if not status_proc.stdout.strip():
            # No changes to commit
            return True

        logger.info("Changes detected. Starting automatic deployment sync...")

        # 2. Add all
        subprocess.run(["git", "add", "."], check=True)

        # 3. Commit
        commit_msg = "system: automatic deployment sync"
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)

        # 4. Push to origin main
        # We assume origin and branch 'main' are correctly configured as per diagnostics
        subprocess.run(["git", "push", "origin", "main"], check=True)

        logger.info("Automatic deployment sync completed successfully.")
        return True

    except Exception as exc:
        logger.error(f"Failed to perform automatic git sync: {exc}")
        return False

if __name__ == "__main__":
    # Manual trigger for testing
    import sys
    success = automatic_sync()
    sys.exit(0 if success else 1)
