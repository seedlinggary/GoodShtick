import sys
import os

# Add the backend root to sys.path so application.py and its imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from application import app  # noqa: F401  (Vercel looks for `app`)
