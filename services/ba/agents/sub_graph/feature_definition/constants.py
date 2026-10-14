"""Flag status constants for Feature Definition evaluation."""

# Data is required but completely empty
MISSING_VALUE = "MISSING_VALUE"

# Data exists but does not meet quantity requirements
FAIL = "FAIL"

# Data meets basic requirements, awaiting LLM semantic evaluation
PENDING_SEMANTIC = "PENDING_SEMANTIC"

# LLM evaluated but data is not yet reasonable (with detail reason)
NOT_YET_REASONABLE = "NOT_YET_REASONABLE"

# Passed all checks (logic + semantic)
PASS = "PASS"

# Advisory only — does not block section completion
WARNING = "WARNING"

# Statuses that block section completion
BLOCKER_STATUSES = frozenset({MISSING_VALUE, FAIL, PENDING_SEMANTIC, NOT_YET_REASONABLE})
