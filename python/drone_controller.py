# Drone Controller

# Build in-memory Python controller for 1 remotely operated drone.
# The controller receives commands from operator and accepts or rejects them.
# It doesn't control real hardware; it only validates commands + updates a small state machine:

# DISARMED → ARMED → FLYING → LANDING → DISARMED.
# FLYING <-> HOVER_FAILSAFE -> LANDING.

# Command            | Valid state               | Result
# `arm`              | `DISARMED`                | state = `ARMED`
# `takeoff`          | `ARMED`                   | state = `FLYING`; altitude = 1.0
# `set_velocity`     | `FLYING`                  | update velocity & last-valid-velocity ts
# `land`             | `FLYING`/`HOVER_FAILSAFE` | state = `LANDING`; velocity = 0
# `landing_complete` | `LANDING`                 | state = `DISARMED`; altitude = 0
# `return_home`      | `FLYING`/`HOVER_FAILSAFE` | state = `LANDING`; velocity = 0

# Each command is either:
# {
#     "command_id": "cmd-001",
#     "type": "arm",
#     "timestamp_ms": 1000,
# }
# or velocity command:
# {
#     "command_id": "cmd-004",
#     "type": "set_velocity",
#     "timestamp_ms": 1300,
#     "forward": 2.0,
#     "right": 0.0,
#     "up": 0.0,
# }

class DroneController:
    def __init__(self, velocity_timeout_ms=500):
        """Start disarmed with 0 velocity."""
        self.velocity_timeout_ms = velocity_timeout_ms
        self.state = "DISARMED"
        self.altitude = 0.0
        self.velocity = {"forward": 0.0, "right": 0.0, "up": 0.0}

        self.last_accepted_timestamp_ms = None
        self.last_valid_velocity_ms = None

        self.acks_by_command_id = {}

    def process_command(self, command):
        """
        Validate and apply 1 command.
        Return an acknowledgement dictionary:
        {
            "command_id": ...,
            "accepted": True or False,
            "reason": "...",
            "state": "...",
        }
        """
        self.validate_command(command)

        # Retry of an already accepted command gets its original acknowledgement.
        if command['command_id'] in self.acks_by_command_id:
            return self.acks_by_command_id[command['command_id']]

        # A new command cannot be older than the latest accepted command.
        if (
            self.last_accepted_timestamp_ms is not None
            and command['timestamp_ms'] < self.last_accepted_timestamp_ms
        ):
            return self.reject(
                command,
                f"{command['type']} command rejected as too old.",
            )

        match command['type']:
            case 'arm':
                if self.state != 'DISARMED':
                    return self.reject(command, 'arm requires DISARMED state')
                self.state = 'ARMED'
            case 'takeoff':
                if self.state != 'ARMED':
                    return self.reject(command, 'takeoff requires ARMED state')
                self.state = 'FLYING'
                self.altitude = 1.0
                self.last_valid_velocity_ms = command['timestamp_ms']
            case 'set_velocity':
                if self.state != 'FLYING':
                    return self.reject(command, 'set_velocity requires FLYING state')
                self.velocity = {
                    "forward": command['forward'],
                    "right": command['right'],
                    "up": command['up'],
                }
                self.last_valid_velocity_ms = command['timestamp_ms']
            case 'land':
                if self.state not in ['FLYING', 'HOVER_FAILSAFE']:
                    return self.reject(command, 'land requires FLYING or HOVER_FAILSAFE state')
                self.state = 'LANDING'
                self.velocity = {"forward": 0.0, "right": 0.0, "up": 0.0}
                self.last_valid_velocity_ms = command['timestamp_ms']
            case 'landing_complete':
                if self.state != 'LANDING':
                    return self.reject(command, 'landing_complete requires LANDING state')
                self.state = 'DISARMED'
                self.altitude = 0.0
            case 'return_home':
                if self.state not in ['FLYING', 'HOVER_FAILSAFE']:
                    return self.reject(command, 'return_home requires FLYING or HOVER_FAILSAFE state')
                self.state = 'LANDING'
                self.velocity = {"forward": 0.0, "right": 0.0, "up": 0.0}
                self.last_valid_velocity_ms = command['timestamp_ms']

        self.last_accepted_timestamp_ms = command['timestamp_ms']

        ack = {
            'command_id': command['command_id'],
            'accepted': True,
            'reason': 'Command applied',
            'state': self.state,
        }

        # only save acknowledgements for accepted commands
        self.acks_by_command_id[command['command_id']] = ack
        return ack

    def reject(self, command, reason):
        return {
            'command_id': command['command_id'],
            'accepted': False,
            'reason': reason,
            'state': self.state,
        }

    def validate_command(self, command):
        required_keys = ['command_id', 'type', 'timestamp_ms']
        has_all_keys = all(k in command for k in required_keys)
        if has_all_keys:
            allowed_commands = ['arm', 'takeoff', 'set_velocity', 'land', 'landing_complete', 'return_home']
            if command['type'] not in allowed_commands:
                raise ValueError('Wrong command type')

            if command['type'] == 'set_velocity':
                has_velocity_keys = all(k in command for k in ['forward', 'right', 'up'])
                if not has_velocity_keys:
                    raise ValueError('Velocity command is missing required keys')
        else:
            raise ValueError('Command is missing required keys')

    def tick(self, now_ms):
        """
        Advance time-dependent safety behavior.

        If flying and no fresh valid velocity command has arrived
        within velocity_timeout_ms, enter HOVER_FAILSAFE.
        """
        if self.state != 'FLYING':
            return

        if now_ms - self.last_valid_velocity_ms >= self.velocity_timeout_ms:
            self.state = 'HOVER_FAILSAFE'
            self.velocity = {"forward": 0.0, "right": 0.0, "up": 0.0}

    def snapshot(self):
        """Return current state and velocity for telemetry."""
        return {
            'state': self.state,
            'altitude': self.altitude,
            'velocity': self.velocity.copy(),
        }

if __name__ == "__main__":
    d = DroneController()
    assert d.state == 'DISARMED'
    assert d.velocity == {"forward": 0.0, "right": 0.0, "up": 0.0}

    try:
        d.process_command({
            'command_id': 'cmd-1',
            'type': 'wrong',
            'timestamp_ms': 100
        })
        assert False, 'ValueError not raised'
    except ValueError as e:
        assert str(e) == 'Wrong command type'

    # Rejects 'takeoff' while DISARMED.
    resp = d.process_command({
        'command_id': 'cmd-1',
        'type': 'takeoff',
        'timestamp_ms': 100
    })
    assert resp['accepted'] is False
    assert resp['reason'] == 'takeoff requires ARMED state'

    # Accepts 'arm' while DISARMED.
    resp = d.process_command({
        'command_id': 'cmd-1',
        'type': 'arm',
        'timestamp_ms': 100
    })
    assert resp['accepted'] is True
    assert resp['state'] == 'ARMED'

    # Repeated accepted command returns its saved acknowledgement.
    # It doesn't change state.
    resp = d.process_command({
        'command_id': 'cmd-1',
        'type': 'arm',
        'timestamp_ms': 100
    })
    assert resp['command_id'] == 'cmd-1'
    assert resp['accepted'] is True
    assert resp['state'] == 'ARMED'

    # Rejects set_velocity while ARMED.
    resp = d.process_command({
        'command_id': 'cmd-2',
        'type': 'set_velocity',
        'timestamp_ms': 101,
        "forward": 2.0,
        "right": 0.0,
        "up": 0.0,
    })
    assert resp['accepted'] is False
    assert resp['reason'] == 'set_velocity requires FLYING state'

    # Accepts 'takeoff' after 'arm'.
    resp = d.process_command({
        'command_id': 'cmd-2',
        'type': 'takeoff',
        'timestamp_ms': 101
    })
    assert resp['accepted'] is True
    assert resp['reason'] == 'Command applied'
    assert resp['state'] == 'FLYING'

    # Accepts 'set_velocity' while FLYING.
    resp = d.process_command({
        'command_id': 'cmd-3',
        'type': 'set_velocity',
        'timestamp_ms': 102,
        "forward": 2.0,
        "right": 0.0,
        "up": 0.0,
    })
    assert resp['accepted'] is True
    assert resp['reason'] == 'Command applied'
    assert d.velocity == {'forward': 2.0, 'right': 0.0, 'up': 0.0}
    assert d.last_valid_velocity_ms == 102

    # Rejects stale (old) 'land' command
    resp = d.process_command({
        'command_id': 'cmd-4',
        'type': 'land',
        'timestamp_ms': 101
    })
    assert resp['accepted'] is False
    assert resp['reason'] == "land command rejected as too old."

    # tick() does nothing before 500 ms boundary
    d.tick(601)  # 499 ms after last valid velocity command.
    assert d.state == "FLYING"
    assert d.velocity["forward"] == 2.0

    # Exactly 500 ms after last valid velocity command,
    # tick() changes state to HOVER_FAILSAFE.
    d.tick(602)
    assert d.state == "HOVER_FAILSAFE"
    assert d.velocity == {
        "forward": 0.0,
        "right": 0.0,
        "up": 0.0,
    }

    # 'land' works from HOVER_FAILSAFE
    resp = d.process_command({
        'command_id': 'cmd-5',
        'type': 'land',
        'timestamp_ms': 105
    })
    assert d.state == 'LANDING'
    assert d.last_valid_velocity_ms == 105

    # 'landing_complete' returns drone to DISARMED
    resp = d.process_command({
        'command_id': 'cmd-6',
        'type': 'landing_complete',
        'timestamp_ms': 106
    })
    assert d.state == 'DISARMED'
    assert d.altitude == 0.0
    print("All tests passed!")

# “I separated command-time validation from time-based safety behavior. process_command handles explicit operator intent, while tick enforces the dead-man failsafe even when no new messages arrive. For production, I’d persist/replicate the command ID and state history, use a monotonic clock, authenticate and authorize commands, and send acknowledgements and telemetry over separate appropriate channels.”

# tick() should be a separate function called periodically by the service/event loop—not only inside process_command().

# A failsafe must activate even if:
# - the operator browser freezes;
# - Wi-Fi/cellular drops;
# - no more commands arrive at all.

# If tick() only runs when a command arrives, it cannot detect silence.

# In a real service, it might run from a small background loop every 50–100 ms—not a traditional once-per-minute cron job:

# while running:
#     controller.tick(monotonic_now_ms())
#     sleep(0.1)

# For now, just expose tick(now_ms) and call it directly in tests. That makes time deterministic.
