from pydantic import BaseModel, ConfigDict, Field

from backend.models.enums import Role


class LoginIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # Sin EmailStr: email-validator rechaza el dominio reservado `.test` de los datos de prueba.
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str
    role: Role
    whatsapp_opt_in: bool
