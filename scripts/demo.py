"""Exercise a running API/worker and optionally verify Compose restart persistence."""

import argparse
import json
import subprocess
import time
from pathlib import Path

import httpx


def wait_ready(client: httpx.Client):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if client.get("/ready").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.5)
    raise RuntimeError("API did not become ready within 60 seconds")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--restart-services", action="store_true")
    parser.add_argument("--save-report", type=Path)
    parser.add_argument("--repair", action="store_true", help="Run controlled fake-provider repair")
    args = parser.parse_args()
    with httpx.Client(base_url=args.url, timeout=10) as client:
        wait_ready(client)
        assert client.get("/health").status_code == 200
        assert client.post("/investigations", json={"fixture_id": "missing"}).status_code == 404
        body = {"fixture_id": "calculator-add"}
        if args.repair:
            body.update(execution_policy="repair", max_model_calls=3, provider="fake")
        response = client.post("/investigations", json=body)
        response.raise_for_status()
        identity = response.json()["id"]
        endpoint = f"/investigations/{identity}/report"
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            response = client.get(endpoint)
            if response.status_code == 200:
                break
            if response.status_code != 409:
                response.raise_for_status()
            time.sleep(0.5)
        response.raise_for_status()
        report = response.json()
        assert report["outcome"] == ("VERIFIED_REPAIR" if args.repair else "DIAGNOSED"), report
        assert report["parsed"]["failures"][0]["exception_type"] == "AssertionError"
        if args.repair:
            assert report["reproduction_status"] == "REPRODUCED"
            assert report["verification_status"] == "PASSED_TARGETED_AND_CONTROLLED_REGRESSION"
        else:
            assert report["verification_status"] == "NOT_RUN"
        for item in report["evidence"]:
            evidence = client.get(f"/investigations/{identity}/evidence/{item['id']}")
            evidence.raise_for_status()
            assert evidence.headers["etag"] == f'"{item["sha256"]}"'
        if args.restart_services:
            subprocess.run(["docker", "compose", "restart", "api", "worker"], check=True)
            wait_ready(client)
            assert client.get(endpoint).json() == report
            print("PASS: identical persisted report after API and worker restart")
        if args.save_report:
            args.save_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        print(f"PASS: live API -> PostgreSQL job -> dedicated worker -> report ({identity})")


if __name__ == "__main__":
    main()
