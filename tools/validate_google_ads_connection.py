
import os
import sys
from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

def validate_connection():
    load_dotenv()
    
    # Load credentials from .env
    credentials = {
        "developer_token": os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
        "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_ADS_CLIENT_SECRET"),
        "refresh_token": os.getenv("GOOGLE_ADS_REFRESH_TOKEN"),
        "login_customer_id": os.getenv("GOOGLE_ADS_MCC_ACCOUNT_ID"),
        "use_proto_plus": True
    }
    
    target_customer_id = os.getenv("GOOGLE_ADS_CHILD_ACCOUNT_ID")
    
    print("--- GOOGLE ADS CONNECTIVITY VALIDATION ---")
    print(f"Target Customer ID: {target_customer_id}")
    print(f"Login (MCC) ID: {credentials['login_customer_id']}")
    
    try:
        # Initialize the client
        client = GoogleAdsClient.load_from_dict(credentials)
        
        # Test 1: Simple query to list accessible customers or get account info
        # We'll try to fetch the account details for the target_customer_id
        ga_service = client.get_service("GoogleAdsService")
        
        query = "SELECT customer.id, customer.descriptive_name FROM customer LIMIT 1"
        
        # Search call to verify access to the target account
        print(f"\nAttempting to query account {target_customer_id}...")
        response = ga_service.search(customer_id=target_customer_id, query=query)
        
        found = False
        for row in response:
            print(f"Connection Successful!")
            print(f"Verified Account ID: {row.customer.id}")
            print(f"Account Name: {row.customer.descriptive_name}")
            found = True
            break
            
        if not found:
            # If search returns nothing but no exception, might be empty or permissions issue
            print("Query returned no results, but no error occurred. Connectivity looks okay.")
            
        return True

    except GoogleAdsException as ex:
        print(f"\nGOOGLE ADS API ERROR:")
        print(f"Request ID: {ex.request_id}")
        for error in ex.failure.errors:
            print(f"\tError with message: {error.message}")
            if error.location:
                for field_path_element in error.location.field_path_elements:
                    print(f"\t\tOn field: {field_path_element.field_name}")
        return False
    except Exception as e:
        print(f"\nUNEXPECTED ERROR: {e}")
        return False

if __name__ == "__main__":
    success = validate_connection()
    if success:
        print("\n[SUCCESS] Connectivity validation passed.")
        sys.exit(0)
    else:
        print("\n[FAILED] Connectivity validation failed.")
        sys.exit(1)
