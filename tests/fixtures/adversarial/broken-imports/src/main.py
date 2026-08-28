# File: main.py
# This file imports modules that DON'T EXIST in the repo.
# DeepDoc should parse this file fine but resolve all imports as UNRESOLVED.
# No fabricated call edges or symbols from the nonexistent files.

from nonexistent_auth_lib import authenticate
from missing_utils import format_response, validate_input
import completely_fake_package as cfp


def handle_request(data: dict) -> dict:
    user = authenticate(data)  # UNRESOLVED - nonexistent_auth_lib doesn't exist
    validate_input(data)  # UNRESOLVED - missing_utils doesn't exist
    return format_response(user)  # UNRESOLVED - missing_utils doesn't exist