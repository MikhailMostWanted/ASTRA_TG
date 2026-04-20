from abc import ABC

from schemas.adapter import AdapterStatus


class AdapterStub(ABC):
    name: str
    notes: str

    def status(self) -> AdapterStatus:
        return AdapterStatus(
            name=self.name,
            implemented=False,
            notes=self.notes,
        )
