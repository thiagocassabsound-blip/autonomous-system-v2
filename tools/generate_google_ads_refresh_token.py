
import os
import sys
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

def generate_refresh_token():
    load_dotenv()
    
    client_id = os.getenv("GOOGLE_ADS_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_ADS_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        print("[ERROR] GOOGLE_ADS_CLIENT_ID or GOOGLE_ADS_CLIENT_SECRET not found in .env")
        return

    # Scopes for Google Ads API
    scopes = ["https://www.googleapis.com/auth/adwords"]

    # Configure the flow for a Desktop App (easier local setup)
    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=scopes,
    )

    # Run the flow to get credentials
    print("\n--- GOOGLE ADS REFRESH TOKEN GENERATOR ---")
    print("1. A browser window will open (or a link will be shown).")
    print("2. Log in with the Google Account that has access to the MCC.")
    print("3. Authorize the application.")
    print("4. Copy the code/token provided.\n")
    
    try:
        # Using a fixed port to make it easier to whitelist in Google Cloud Console
        # If the user has a "Web Application" internal client, they must add
        # http://localhost:8082/ to the "Authorized redirect URIs"
        credentials = flow.run_local_server(host='localhost', port=8082)
        
        print("\n[SUCCESS] New Refresh Token generated:")
        print(f"\nGOOGLE_ADS_REFRESH_TOKEN={credentials.refresh_token}\n")
        print("Please copy this value to your .env file and replace the old one.")
        
    except Exception as e:
        print(f"\n[ERROR] Failed to generate token: {e}")

if __name__ == "__main__":
    generate_refresh_token()
