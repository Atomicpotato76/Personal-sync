import uuid
from typing import Optional

import requests


class RouterClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self.session_id: Optional[str] = None

    def chat(
        self,
        message: str,
        preset: Optional[str] = None,
        profile: str = "full",
        use_session: bool = False,
    ) -> dict:
        payload = {"message": message, "profile": profile}
        if preset:
            payload["preset"] = preset
        if use_session:
            if not self.session_id:
                self.session_id = str(uuid.uuid4())
            payload["session_id"] = self.session_id

        response = requests.post(f"{self.base_url}/chat", json=payload, timeout=180)
        response.raise_for_status()
        data = response.json()

        if use_session:
            self.session_id = data.get("session_id", self.session_id)

        return data

    def new_session(self) -> None:
        self.session_id = None
