package main

import (
	"testing"
	"time"
)

func newCommand(action, id string, sentAt time.Time) command {
	return command{
		Type:   "command",
		ID:     id,
		Action: action,
		SentAt: sentAt,
	}
}

func makeFlyingDrone(t *testing.T) *drone {
	t.Helper()

	d := newDrone()

	arm := d.apply(newCommand("arm", "arm-1", time.Now()))
	if !arm.Accepted {
		t.Fatalf("arm rejected: %s", arm.Reason)
	}

	takeoff := d.apply(newCommand("takeoff", "takeoff-1", time.Now()))
	if !takeoff.Accepted {
		t.Fatalf("takeoff rejected: %s", takeoff.Reason)
	}

	return d
}

func TestCannotTakeoffWhileDisarmed(t *testing.T) {
	d := newDrone()

	ack := d.apply(newCommand("takeoff", "takeoff-1", time.Now()))

	if ack.Accepted {
		t.Fatal("takeoff while disarmed was accepted")
	}
	if d.state != stateDisarmed {
		t.Fatalf("state = %s, want %s", d.state, stateDisarmed)
	}
}

func TestValidArmThenTakeoffTransition(t *testing.T) {
	d := newDrone()

	arm := d.apply(newCommand("arm", "arm-1", time.Now()))
	if !arm.Accepted || d.state != stateArmed {
		t.Fatalf("arm: accepted=%v state=%s", arm.Accepted, d.state)
	}

	takeoff := d.apply(newCommand("takeoff", "takeoff-1", time.Now()))
	if !takeoff.Accepted || d.state != stateFlying {
		t.Fatalf("takeoff: accepted=%v state=%s", takeoff.Accepted, d.state)
	}
	if d.altitudeM != 5 {
		t.Fatalf("altitude = %.1f, want 5.0", d.altitudeM)
	}
}

func TestStaleCommandRejected(t *testing.T) {
	d := newDrone()

	staleTime := time.Now().Add(-3 * time.Second)
	ack := d.apply(newCommand("arm", "stale-arm-1", staleTime))

	if ack.Accepted {
		t.Fatal("stale command was accepted")
	}
	if d.state != stateDisarmed {
		t.Fatalf("state = %s, want %s", d.state, stateDisarmed)
	}
}

func TestDuplicateCommandDoesNotReapplyTransition(t *testing.T) {
	d := newDrone()

	takeoffCommand := newCommand("takeoff", "takeoff-1", time.Now())

	arm := d.apply(newCommand("arm", "arm-1", time.Now()))
	if !arm.Accepted {
		t.Fatalf("arm rejected: %s", arm.Reason)
	}

	first := d.apply(takeoffCommand)
	if !first.Accepted {
		t.Fatalf("first takeoff rejected: %s", first.Reason)
	}

	altitudeBeforeRetry := d.altitudeM

	retry := d.apply(takeoffCommand)
	if !retry.Accepted {
		t.Fatalf("duplicate retry was not acknowledged: %s", retry.Reason)
	}
	if retry.Reason != "duplicate command ID: acknowledged without reapplying" {
		t.Fatalf("unexpected duplicate reason: %q", retry.Reason)
	}
	if d.state != stateFlying {
		t.Fatalf("state = %s, want %s", d.state, stateFlying)
	}
	if d.altitudeM != altitudeBeforeRetry {
		t.Fatalf("duplicate changed altitude from %.1f to %.1f", altitudeBeforeRetry, d.altitudeM)
	}
}

func TestRejectedCommandIDCanBeRetried(t *testing.T) {
	d := newDrone()
	command := newCommand("takeoff", "takeoff-retry-1", time.Now())

	rejected := d.apply(command)
	if rejected.Accepted {
		t.Fatal("takeoff while disarmed was accepted")
	}

	if arm := d.apply(newCommand("arm", "arm-retry-1", time.Now())); !arm.Accepted {
		t.Fatalf("arm rejected: %s", arm.Reason)
	}

	retried := d.apply(command)
	if !retried.Accepted {
		t.Fatalf("retry of previously rejected command was rejected: %s", retried.Reason)
	}
	if d.state != stateFlying {
		t.Fatalf("state = %s, want %s", d.state, stateFlying)
	}
}

func TestDuplicateVelocityCommandDoesNotDelayFailsafe(t *testing.T) {
	d := makeFlyingDrone(t)
	sentAt := time.Now()
	move := newCommand("set_velocity", "velocity-duplicate-1", sentAt)
	move.Velocity = velocity{Forward: 1}

	if ack := d.apply(move); !ack.Accepted {
		t.Fatalf("velocity command rejected: %s", ack.Reason)
	}
	if ack := d.apply(move); !ack.Accepted {
		t.Fatalf("duplicate velocity command was not acknowledged: %s", ack.Reason)
	}

	triggered := d.enforceVelocityFailsafe(
		sentAt.Add(velocityFailsafeTimeout + time.Millisecond),
	)
	if !triggered {
		t.Fatal("duplicate velocity command incorrectly delayed failsafe")
	}
	if d.state != stateHoverFailsafe {
		t.Fatalf("state = %s, want %s", d.state, stateHoverFailsafe)
	}
}

func TestOlderVelocityCommandRejected(t *testing.T) {
	d := makeFlyingDrone(t)
	newer := newCommand("set_velocity", "velocity-new-1", time.Now())
	newer.Velocity = velocity{Forward: 1}

	if ack := d.apply(newer); !ack.Accepted {
		t.Fatalf("newer velocity command rejected: %s", ack.Reason)
	}

	older := newCommand(
		"set_velocity",
		"velocity-old-1",
		newer.SentAt.Add(-time.Millisecond),
	)
	older.Velocity = velocity{Right: 1}
	ack := d.apply(older)
	if ack.Accepted {
		t.Fatal("older velocity command was accepted")
	}
	if d.velocity != newer.Velocity {
		t.Fatalf("velocity = %+v, want %+v", d.velocity, newer.Velocity)
	}
}

func TestLossOfVelocityCommandsTriggersFailsafe(t *testing.T) {
	d := makeFlyingDrone(t)

	move := newCommand("set_velocity", "velocity-1", time.Now())
	move.Velocity = velocity{Forward: 1}

	ack := d.apply(move)
	if !ack.Accepted {
		t.Fatalf("velocity command rejected: %s", ack.Reason)
	}

	triggered := d.enforceVelocityFailsafe(
		time.Now().Add(velocityFailsafeTimeout + time.Millisecond),
	)

	if !triggered {
		t.Fatal("failsafe did not trigger")
	}
	if d.state != stateHoverFailsafe {
		t.Fatalf("state = %s, want %s", d.state, stateHoverFailsafe)
	}
	if d.velocity != (velocity{}) {
		t.Fatalf("velocity = %+v, want zero velocity", d.velocity)
	}
	if d.failsafeReason == "" {
		t.Fatal("failsafe reason was empty")
	}
}

func TestLandReturnsToSafeState(t *testing.T) {
	d := makeFlyingDrone(t)

	ack := d.apply(newCommand("land", "land-1", time.Now()))
	if !ack.Accepted {
		t.Fatalf("land rejected: %s", ack.Reason)
	}
	if d.state != stateLanding {
		t.Fatalf("state = %s, want %s", d.state, stateLanding)
	}
	if d.velocity != (velocity{}) {
		t.Fatalf("velocity = %+v, want zero velocity", d.velocity)
	}

	for range 5 {
		d.getTelemetry()
	}

	if d.state != stateDisarmed {
		t.Fatalf("state = %s, want %s", d.state, stateDisarmed)
	}
	if d.altitudeM != 0 {
		t.Fatalf("altitude = %.1f, want 0", d.altitudeM)
	}
}
