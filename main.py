from States.ExampleState import StateA
from StateMachine.StateMachine import StateMachine

if __name__ == "__main__":
    state_a = StateA()
    state_machine = StateMachine(state_a)

    state_machine.run()
