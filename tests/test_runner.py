#!/usr/bin/env python3
"""
Test Runner for Flash Loan Arbitrage Bot
Runs simulations and integration tests
"""

import asyncio
import subprocess
import sys
import os
from pathlib import Path

def run_simulation_test():
    """Run paper trading simulation"""
    print("🧪 Running Paper Trading Simulation...")
    try:
        paper_trader_path = Path(__file__).parent.parent / "scripts" / "paper_trader.py"
        result = subprocess.run([
            sys.executable, str(paper_trader_path)
        ], capture_output=True, text=True, timeout=60)

        print("📄 Simulation Output:")
        print(result.stdout)
        if result.stderr:
            print("⚠️  Simulation Errors:")
            print(result.stderr)

        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print("⏰ Simulation timed out")
        return False
    except Exception as e:
        print(f"❌ Simulation failed: {e}")
        return False

def check_code_syntax():
    """Check Python syntax of main files"""
    print("🧪 Checking Python syntax...")
    files_to_check = [
        "arb_bot.py",
        "paper_trader.py",
        "src/ingest/tx_builder.py",
        "src/ingest/jito_bundle_client.py"
    ]

    all_good = True
    for file_path in files_to_check:
        if os.path.exists(file_path):
            try:
                result = subprocess.run([
                    sys.executable, "-m", "py_compile", file_path
                ], capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"✅ {file_path}")
                else:
                    print(f"❌ {file_path}: {result.stderr}")
                    all_good = False
            except Exception as e:
                print(f"❌ {file_path}: {e}")
                all_good = False
        else:
            print(f"⚠️  {file_path} not found")

    return all_good

def run_pytest():
    """Run pytest with parallel execution"""
    print("🧪 Running Pytest Suite...")
    try:
        result = subprocess.run([
            sys.executable, "-m", "pytest",
            "--tb=short",
            "tests/"
        ], capture_output=True, text=True, timeout=300)

        print("📄 Pytest Output:")
        print(result.stdout)
        if result.stderr:
            print("⚠️  Pytest Errors:")
            print(result.stderr)

        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print("⏰ Pytest timed out")
        return False
    except Exception as e:
        print(f"❌ Pytest failed: {e}")
        return False

def run_integration_test():
    """Run a quick integration test"""
    print("🧪 Running Integration Test...")
    try:
        # Test importing main modules
        sys.path.insert(0, '.')
        import arb_bot
        import paper_trader

        print("✅ All main modules imported successfully")
        return True
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("🚀 Flash Loan Arbitrage Bot Test Suite")
    print("=" * 50)

    tests = [
        ("Syntax Check", check_code_syntax),
        ("Pytest Suite", run_pytest),
        ("Integration Test", run_integration_test),
        ("Simulation Test", run_simulation_test),
    ]

    results = []
    for test_name, test_func in tests:
        print(f"\n🔬 {test_name}")
        success = test_func()
        results.append((test_name, success))
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"Result: {status}")

    print("\n" + "=" * 50)
    print("📊 Test Results Summary:")
    passed = 0
    total = len(results)
    for test_name, success in results:
        status = "✅" if success else "❌"
        print(f"  {status} {test_name}")
        if success:
            passed += 1

    print(f"\n🎯 Overall: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! Ready for production.")
        return 0
    else:
        print("💥 Some tests failed. Please review and fix issues.")
        return 1

if __name__ == "__main__":
    sys.exit(main())