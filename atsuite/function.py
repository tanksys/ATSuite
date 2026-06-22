from abc import ABC, abstractmethod

class FunctionBase(ABC):
    @abstractmethod
    def deploy(self) -> str:
        pass