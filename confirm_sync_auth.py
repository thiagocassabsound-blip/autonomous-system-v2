import os
import sys
from dotenv import load_dotenv

# Ensure we load BEFORE importing the module
load_dotenv(override=True)

# Add current directory to path
sys.path.append(os.getcwd())

from api.routes.dashboard_routes import DASHBOARD_USER, DASHBOARD_PASSWORD

def confirm():
    # Load from .env manually for comparison
    eu = os.getenv('ADMIN_USERNAME')
    ep = os.getenv('ADMIN_PASSWORD')

    ru = DASHBOARD_USER
    rp = DASHBOARD_PASSWORD

    outdated = (ru != eu or rp != ep)

    print(f"RUNTIME_USERNAME: {ru}")
    print(f"RUNTIME_PASSWORD_LENGTH: {len(rp) if rp else 0}")
    print(f"ENV_USERNAME: {eu}")
    print(f"ENV_PASSWORD_LENGTH: {len(ep) if ep else 0}")
    print(f"RUNTIME_ENV_OUTDATED: {outdated}")

if __name__ == '__main__':
    confirm()
