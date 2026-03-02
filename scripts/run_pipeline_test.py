#!/usr/bin/env python3
"""
Pipeline Test Runner for BaselineMLB
Tests all data pipelines in sequence to verify Week 1 functionality.

Usage: python scripts/run_pipeline_test.py
"""

import os
import subprocess
import sys
from datetime import datetime

# Ensure we're running from project root
if not os.path.exists('pipeline'):
    print("❌ Error: Run this script from the project root directory")
    sys.exit(1)

class PipelineTest:
    def __init__(self):
        self.results = []
        self.start_time = datetime.now()

    def run_test(self, name, command, description):
        """Run a single pipeline test"""
        print(f"\n{'='*60}")
        print(f"🔄 Testing: {name}")
        print(f"📝 {description}")
        print(f"{'='*60}")

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120
            )

            success = result.returncode == 0

            if success:
                print(f"✅ {name} - PASSED")
                self.results.append((name, "PASS", result.stdout))
            else:
                print(f"❌ {name} - FAILED")
                print(f"Error: {result.stderr}")
                self.results.append((name, "FAIL", result.stderr))

            return success

        except subprocess.TimeoutExpired:
            print(f"⏰ {name} - TIMEOUT")
            self.results.append((name, "TIMEOUT", "Test exceeded 120s timeout"))
            return False
        except Exception as e:
            print(f"💥 {name} - ERROR: {str(e)}")
            self.results.append((name, "ERROR", str(e)))
            return False

    def print_summary(self):
        """Print test summary"""
        duration = (datetime.now() - self.start_time).total_seconds()

        print(f"\n\n{'='*60}")
        print("📊 WEEK 1 PIPELINE TEST SUMMARY")
        print(f"{'='*60}")
        print(f"Total Duration: {duration:.2f}s\n")

        passed = sum(1 for _, status, _ in self.results if status == "PASS")
        failed = sum(1 for _, status, _ in self.results if status == "FAIL")
        errors = sum(1 for _, status, _ in self.results if status in ["TIMEOUT", "ERROR"])

        for name, status, _ in self.results:
            icon = "✅" if status == "PASS" else "❌"
            print(f"{icon} {name}: {status}")

        print(f"\n{'='*60}")
        print(f"Results: {passed} passed, {failed} failed, {errors} errors")
        print(f"{'='*60}\n")

        return failed == 0 and errors == 0

def main():
    tester = PipelineTest()

    print("""
    ╔════════════════════════════════════════════════════════╗
    ║   BASELINEMLB - WEEK 1 PIPELINE TEST SUITE            ║
    ║   Testing: Data pipelines, projections, dashboard     ║
    ╚════════════════════════════════════════════════════════╝
    """)

    # Test 1: Check environment variables
    tester.run_test(
        "Environment Check",
        "python -c 'import os; assert os.getenv(\"SUPABASE_URL\"), \"Missing SUPABASE_URL\"; print(\"\u2705 Environment OK\")'",
        "Verify Supabase credentials are configured"
    )

    # Test 2: Fetch Players
    tester.run_test(
        "Fetch Players Pipeline",
        "python pipeline/fetch_players.py",
        "Load MLB 40-man rosters into Supabase (all 30 teams)"
    )

    # Test 3: Fetch Games
    tester.run_test(
        "Fetch Games Pipeline",
        "python pipeline/fetch_games.py",
        "Load yesterday's MLB schedule into Supabase"
    )

    # Test 4: Fetch Props
    tester.run_test(
        "Fetch Props Pipeline",
        "python pipeline/fetch_props.py",
        "Load player props from The Odds API"
    )

    # Test 5: Run Projection Model
    tester.run_test(
        "Projection Model",
        "python analysis/projection_model.py",
        "Generate glass-box projections for today's players"
    )

    # Test 6: Verify dashboard files exist
    tester.run_test(
        "Dashboard Files Check",
        "test -f dashboard/index.html && echo '\u2705 Dashboard exists'",
        "Verify dashboard HTML is present"
    )

    # Test 7: Check Supabase connection
    tester.run_test(
        "Supabase Connection Test",
        "python -c 'from supabase import create_client; import os; client = create_client(os.getenv(\"SUPABASE_URL\"), os.getenv(\"SUPABASE_ANON_KEY\")); print(\"\u2705 Supabase connected\")'",
        "Verify database connectivity"
    )

    # Print final summary
    success = tester.print_summary()

    if success:
        print("""
        🎉 SUCCESS! All Week 1 pipelines are operational.
        
        Next steps:
        1. Check GitHub Actions logs for automated runs
        2. View dashboard at: https://nrlefty5.github.io/baselinemlb
        3. Verify data quality in Supabase dashboard
        """)
        sys.exit(0)
    else:
        print("""
        ⚠️  SOME TESTS FAILED
        
        Troubleshooting:
        1. Verify .env file has correct credentials
        2. Check Supabase project is active
        3. Review error logs above
        4. Ensure dependencies are installed: pip install -r requirements.txt
        """)
        sys.exit(1)

if __name__ == "__main__":
    main()
