#!/usr/bin/env python
"""Wrapper to seed DB from project root — for Railway shell and local Windows.
Usage:
  python seed.py                 # seeds via backend/SampleDataSeed.py
  AUTO_SEED=0 python seed.py     # skip auto-seed
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
try:
    from SampleDataSeed import seed
    print("[*] Running SampleDataSeed.seed() from project root...")
    seed()
except Exception as e:
    print(f"[!] Seed failed: {e}")
    sys.exit(1)
