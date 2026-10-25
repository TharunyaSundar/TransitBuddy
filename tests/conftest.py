"""Shared test setup: keep the trip planner off unless a test passes its own TravelService, so tests never
call the real Never Late API (load_dotenv doesn't override a variable that's already set)."""
import os

os.environ["NEVER_LATE_TOKEN"] = ""
