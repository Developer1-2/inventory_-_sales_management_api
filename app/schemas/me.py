from pydantic import BaseModel


class AuthMeResponse(BaseModel):
    user_id: int
    business_id: int
    role: str
    membership_id: int
    location_ids: list[int] | str
