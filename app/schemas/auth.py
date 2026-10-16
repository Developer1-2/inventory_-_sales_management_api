from pydantic import BaseModel, EmailStr


class RegisterBusinessRequest(BaseModel):
    business_name: str
    owner_name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    business_id: int | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    business_id: int
    role: str
    membership_id: int


class BusinessChoice(BaseModel):
    business_id: int
    business_name: str


class LoginBusinessChoiceResponse(BaseModel):
    businesses: list[BusinessChoice]
