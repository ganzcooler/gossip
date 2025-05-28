# Basisklasse für States
class BaseState:
    def execute(self):
        raise NotImplementedError("Die Methode muss vond er Subklasse implementiert werden.")