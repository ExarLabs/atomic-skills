#!/usr/bin/env python3
"""Régi nevű belépő (felmero.py): ugyanazt futtatja, mint az erp_plan.py."""
import os, runpy, sys

sys.argv[0] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "erp_plan.py")
runpy.run_path(sys.argv[0], run_name="__main__")
