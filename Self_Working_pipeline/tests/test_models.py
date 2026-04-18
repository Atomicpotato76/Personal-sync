import pytest
from pydantic import ValidationError

from contracts.models import UserRequest


def test_user_request_requires_text() -> None:
    with pytest.raises(ValidationError):
        UserRequest(raw_request="")
