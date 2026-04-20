from pydantic import BaseModel


class AdapterStatus(BaseModel):
    name: str
    implemented: bool
    notes: str
