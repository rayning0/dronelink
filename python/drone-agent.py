# A small in-memory drone state machine.
# DISARMED → ARMED → FLYING → LANDING → DISARMED

from enum import Enum

class State(Enum):
    DISARMED = "disarmed"
    ARMED = "armed"
    FLYING = "flying"
    LANDING = "landing"


NEXT = {
    State.DISARMED: {"arm": State.ARMED},
    State.ARMED: {"takeoff": State.FLYING},
    State.FLYING: {"land": State.LANDING},
    State.LANDING: {"complete": State.DISARMED},
}


class Drone:
    def __init__(self):
        self.state = State.DISARMED

    def send(self, command):
        next_state = NEXT[self.state].get(command)
        if next_state is None:
            raise ValueError(f"{command} is invalid in {self.state.value}")
        self.state = next_state


if __name__ == "__main__":
    # Correct order: every command reaches the expected next state.
    drone = Drone()
    for command, expected in (
        ("arm", State.ARMED),
        ("takeoff", State.FLYING),
        ("land", State.LANDING),
        ("complete", State.DISARMED),
    ):
        drone.send(command)
        assert drone.state == expected

    # Wrong order: takeoff before arm must be rejected.
    drone = Drone()
    try:
        drone.send("takeoff")
        assert False, "takeoff should fail while disarmed"
    except ValueError:
        pass

    print("all state-machine assertions passed")
