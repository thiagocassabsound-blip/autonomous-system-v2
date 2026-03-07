"""
infra/deploy/vercel_adapter.py

Infrastructure adapter to deploy landing pages to Vercel via API.
Converted from V1 deploy/manager.py.
Returns deployment URL and avoids orchestrating state.
"""
import os
from infrastructure.logger import get_logger

logger = get_logger("VercelAdapter")

class VercelAdapter:
    def __init__(self):
        self.token = os.getenv("VERCEL_API_TOKEN")
        self.domain = os.getenv("VERCEL_DOMAIN", "localhost")
        
        if not self.token:
            logger.warning("[VercelAdapter] VERCEL_API_TOKEN is missing. Deployments will run in simulation mode.")

    def _get_files_payload(self, build_directory: str) -> list:
        files = []
        if not os.path.exists(build_directory):
            logger.error(f"[VercelAdapter] Build directory {build_directory} not found.")
            return files
            
        for root, _, filenames in os.walk(build_directory):
            for filename in filenames:
                file_path = os.path.join(root, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        data = f.read()
                    
                    rel_path = os.path.relpath(file_path, build_directory).replace("\\", "/")
                    files.append({
                        "file": rel_path,
                        "data": data
                    })
                except Exception as e:
                    logger.warning(f"[VercelAdapter] Could not read {file_path}: {e}")
        return files

    def deploy_site(self, project_name: str, build_directory: str) -> str:
        """
        Deploys the static files in build_directory to Vercel.
        Returns the deployment URL.
        """
        if not self.token:
            logger.info(f"[VercelAdapter] Simulation mode: Deploying '{project_name}' locally from '{build_directory}'")
            return f"http://{self.domain}/{project_name}"

        logger.info(f"[VercelAdapter] Deploying '{project_name}' to Vercel...")
        
        files_payload = self._get_files_payload(build_directory)
        if not files_payload:
            return None
            
        url = "https://api.vercel.com/v13/deployments"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "name": project_name,
            "files": files_payload,
            "projectSettings": {
                "framework": None
            }
        }
        
        try:
            import requests
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                deploy_url = f"https://{data.get('url')}"
                logger.info(f"[VercelAdapter] Vercel deploy success: {deploy_url}")
                return deploy_url
            else:
                logger.error(f"[VercelAdapter] Deploy failed [{response.status_code}]: {response.text}")
                return None
        except Exception as e:
            logger.error(f"[VercelAdapter] Exception requesting Vercel API: {e}")
            return None

# Singleton export
vercel_adapter = VercelAdapter()

def deploy_site(project_name: str, build_directory: str) -> str:
    """Wrapper for external calls."""
    return vercel_adapter.deploy_site(project_name, build_directory)
