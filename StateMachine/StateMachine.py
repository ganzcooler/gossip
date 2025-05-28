from StateMachine.BaseState import BaseState

class StateMachine:
    def __init__(self, inital_state: BaseState):
        self.current_state = inital_state

    def set_state(self, new_state: BaseState):
        self.current_state = new_state

    def run(self):
        self.current_state.execute()