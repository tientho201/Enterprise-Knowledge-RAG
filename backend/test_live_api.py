import httpx
import sys

def test_api():
    base_url = "http://127.0.0.1:8000/api/v1"
    
    # 1. Login
    login_payload = {
        "email": "user@example.com",
        "password": "password123"
    }
    print("Logging in...")
    try:
        r = httpx.post(f"{base_url}/auth/login", json=login_payload)
        print("Login Status:", r.status_code)
        if r.status_code != 200:
            # Try registering
            print("Login failed. Registering...")
            r = httpx.post(f"{base_url}/auth/register", json=login_payload)
            print("Register Status:", r.status_code)
            r = httpx.post(f"{base_url}/auth/login", json=login_payload)
            print("Login Status (After Reg):", r.status_code)
        
        tokens = r.json()
        token = tokens["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # 2. Chat with search_tool=True
        chat_payload = {
            "message": "Who won the UEFA Euro 2024 final and what was the score?",
            "search_tool": True
        }
        print("\nSending chat request (search_tool=True)...")
        r = httpx.post(f"{base_url}/chat", json=chat_payload, headers=headers, timeout=30.0)
        print("Chat Status:", r.status_code)
        print("Chat Response JSON:", r.json())
        
        # 3. Get history to verify it was saved in Supabase
        print("\nFetching history...")
        r = httpx.get(f"{base_url}/chat/history", headers=headers)
        print("History Status:", r.status_code)
        print("History Count:", len(r.json()))
        print("History Items:", r.json()[:3])
        
    except Exception as e:
        print("Error connecting to live API:", e)

if __name__ == "__main__":
    test_api()
