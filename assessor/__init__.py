"""Enterprise AI Architecture & PoC Readiness Assessment Agent package."""

import os

__version__ = "1.0.0"
__project_id__ = os.environ.get("GOOGLE_CLOUD_PROJECT", "ai-readiness-assessor")
__project_number__ = os.environ.get("GOOGLE_CLOUD_PROJECT_NUMBER", "123456789012")
