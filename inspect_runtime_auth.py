import os
import sys

# Add current directory to path
sys.path.append(os.getcwd())

from api.routes.dashboard_routes import DASHBOARD_USER, DASHBOARD_PASSWORD

def inspect():
    # Load from .env manually for comparison
    eu = ""
    ep = ""
    if os.path.exists('.env'):
        with open('.env') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, val = line.split('=', 1)
                    if key == 'ADMIN_USERNAME':
                        eu = val.strip()
                    if key == 'ADMIN_PASSWORD':
                        ep = val.strip()

    ru = DASHBOARD_USER
    rp = DASHBOARD_PASSWORD

    outdated = (ru != eu or rp != ep)

    print(f"RUNTIME_USERNAME: {ru}")
    print(f"RUNTIME_PASSWORD_LENGTH: {len(rp) if rp else 0}")
    print(f"ENV_USERNAME: {eu}")
    print(f"ENV_PASSWORD_LENGTH: {len(ep) if ep else 0}")
    print(f"RUNTIME_ENV_OUTDATED: {outdated}")

if __name__ == '__main__':
    inspect()
