import sys
import time
import requests

API_URL = "http://localhost:8000"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASS = "change-me-before-deploy"

TEST_CASES = [
    {
        "name": "Python: A+B (Correct -> AC)",
        "problem_id": 1,
        "language_id": "python3",
        "code": "print(sum(map(int, input().split())))",
        "expected_verdict": "AC",
    },
    {
        "name": "C++17: A+B (Correct -> AC)",
        "problem_id": 1,
        "language_id": "cpp17",
        "code": "#include <iostream>\nint main() { int a, b; if (std::cin >> a >> b) std::cout << a + b << std::endl; return 0; }",
        "expected_verdict": "AC",
    },
    {
        "name": "Python: A+B (Wrong Output -> WA)",
        "problem_id": 1,
        "language_id": "python3",
        "code": "print(0)",
        "expected_verdict": "WA",
    },
    {
        "name": "Python: A+B (Division by Zero -> RE)",
        "problem_id": 1,
        "language_id": "python3",
        "code": "x = 1 / 0",
        "expected_verdict": "RE",
    },
    {
        "name": "Python: A+B (Infinite Loop -> TLE)",
        "problem_id": 1,
        "language_id": "python3",
        "code": "while True: pass",
        "expected_verdict": "TLE",
    },
]

def run():
    print("=" * 65)
    print(" 🚀 STARTING FULL AUTOMATED EVALUATION PIPELINE TEST")
    print("=" * 65)

    # 1. Authenticate
    print("\n[1/3] Authenticating with API...")
    login_res = requests.post(
        f"{API_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
    )
    if login_res.status_code != 200:
        print(f"❌ Login failed: {login_res.text}")
        sys.exit(1)
    
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("✔ Authentication successful (JWT token acquired)")

    # 2. Dispatch and Poll
    print("\n[2/3] Submitting test payloads through RabbitMQ/Celery/Sandbox...")
    results = []
    
    for case in TEST_CASES:
        sub_res = requests.post(
            f"{API_URL}/api/submissions",
            headers=headers,
            json={
                "problem_id": case["problem_id"],
                "language_id": case["language_id"],
                "source_code": case["code"],
            },
        )
        if sub_res.status_code not in (200, 202):
            results.append((case["name"], case["expected_verdict"], "FAILED_SUBMIT", "ERROR"))
            continue
            
        sub_id = sub_res.json()["id"]
        print(f"  -> Dispatched: {case['name']} (ID: {sub_id})")

        # Poll status
        verdict = "PENDING"
        for _ in range(30):
            time.sleep(1)
            status_res = requests.get(f"{API_URL}/api/submissions/{sub_id}", headers=headers).json()
            if status_res.get("status") in ("COMPLETED", "ERROR"):
                verdict = status_res.get("verdict", "ERROR")
                break
        
        status_ok = verdict == case["expected_verdict"]
        results.append((case["name"], case["expected_verdict"], verdict, "PASS" if status_ok else "FAIL"))

    # 3. Print Report
    print("\n[3/3] Generating Pipeline Verification Report:")
    print("=" * 65)
    print(f"{'Test Case':<36} | {'Expected':<8} | {'Actual':<8} | {'Result'}")
    print("-" * 65)
    all_passed = True
    for name, exp, act, res in results:
        flag = "✅" if res == "PASS" else "❌"
        print(f"{name:<36} | {exp:<8} | {act:<8} | {flag} {res}")
        if res != "PASS":
            all_passed = False
    print("=" * 65)

    if all_passed:
        print("🎉 All verdicts (AC, WA, RE, TLE) handled accurately by the engine!")
    else:
        print("⚠️ Some verdicts did not match expectations.")

if __name__ == "__main__":
    run()
