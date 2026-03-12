import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_PATH = os.path.join(BASE_DIR, ".env")

class IntegrationValidator:
    """
    Validates external system integrations ensuring credentials
    for core runtime actions are present.
    """
    REQUIRED_ADS_VARS = [
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_MCC_ACCOUNT_ID",
        "GOOGLE_ADS_CHILD_ACCOUNT_ID"
    ]

    @staticmethod
    def validate():
        results = {
            "status": "OK",
            "missing_credentials": [],
            "violations": []
        }
        
        load_dotenv(dotenv_path=ENV_PATH)
        
        # Google Ads check (Mandatory for P10.4)
        for var in IntegrationValidator.REQUIRED_ADS_VARS:
            if not os.environ.get(var):
                results["missing_credentials"].append(var)
                results["status"] = "ERROR"
                results["violations"].append(f"missing_credentials_alert: {var}")
                
        # Base Integrations Checks
        base_vars = ["OPENAI_API_KEY", "STRIPE_SECRET_KEY", "SERPER_API_KEY", "RESEND_API_KEY"]
        for var in base_vars:
            if not os.environ.get(var):
                results["missing_credentials"].append(var)
                results["status"] = "ERROR"
                results["violations"].append(f"missing_credentials_alert: {var}")
                
        return results
