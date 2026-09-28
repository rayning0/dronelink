package main

import (
	"context"
	"encoding/json"
	"log"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

	lksdk "github.com/livekit/server-sdk-go/v2"
)

const (
	roomName         = "demo"
	agentIdentity    = "drone-agent-01"
	operatorIdentity = "operator"
)

type flightState string

const (
	stateDisarmed           flightState = "DISARMED"
	stateArmed              flightState = "ARMED"
	stateFlying             flightState = "FLYING"
	stateLanding            flightState = "LANDING"
	stateHoverFailsafe      flightState = "HOVER_FAILSAFE"
	velocityFailsafeTimeout             = 500 * time.Millisecond
)

type velocity struct {
	Forward float64 `json:"forward"`
	Right   float64 `json:"right"`
	Up      float64 `json:"up"`
}

type command struct {
	Type     string    `json:"type"`
	ID       string    `json:"id"`
	Action   string    `json:"action"`
	SentAt   time.Time `json:"sentAt"`
	Velocity velocity  `json:"velocity"`
}

type acknowledgement struct {
	Type      string      `json:"type"`
	CommandID string      `json:"commandId"`
	Action    string      `json:"action"`
	Accepted  bool        `json:"accepted"`
	Reason    string      `json:"reason,omitempty"`
	State     flightState `json:"state"`
	SentAt    time.Time   `json:"sentAt"`
}

type telemetry struct {
	Type           string      `json:"type"`
	State          flightState `json:"state"`
	BatteryPct     float64     `json:"batteryPct"`
	AltitudeM      float64     `json:"altitudeM"`
	Velocity       velocity    `json:"velocity"`
	FailsafeReason string      `json:"failsafeReason,omitempty"`
	LastCommandAt  *time.Time  `json:"lastCommandAt,omitempty"`
	SentAt         time.Time   `json:"sentAt"`
}

type drone struct {
	mu                     sync.Mutex
	state                  flightState
	batteryPct             float64
	altitudeM              float64
	velocity               velocity
	failsafeReason         string
	lastCommandAt          *time.Time
	lastVelocityAt         *time.Time
	lastVelocityReceivedAt *time.Time
	lastTelemetryAt        time.Time
}

func newDrone() *drone {
	return &drone{
		state:      stateDisarmed,
		batteryPct: 100,
	}
}

func (d *drone) apply(command command) acknowledgement {
	d.mu.Lock()
	defer d.mu.Unlock()

	now := time.Now()

	ack := acknowledgement{
		Type:      "ack",
		CommandID: command.ID,
		Action:    command.Action,
		State:     d.state,
		SentAt:    now,
	}

	if command.ID == "" {
		ack.Reason = "command ID is required"
		return ack
	}

	if command.SentAt.IsZero() ||
		now.Sub(command.SentAt) > 2*time.Second ||
		command.SentAt.After(now.Add(2*time.Second)) {
		ack.Reason = "command timestamp is invalid or stale"
		return ack
	}

	if command.Action == "set_velocity" &&
		d.lastVelocityAt != nil &&
		!command.SentAt.After(*d.lastVelocityAt) {
		ack.Reason = "velocity command is older than the latest accepted velocity"
		return ack
	}

	switch command.Action {
	case "arm":
		if d.state != stateDisarmed {
			ack.Reason = "drone must be disarmed before arming"
			return ack
		}
		d.state = stateArmed

	case "takeoff":
		if d.state != stateArmed {
			ack.Reason = "takeoff requires ARMED state"
			return ack
		}
		d.state = stateFlying
		d.altitudeM = 5

	case "set_velocity":
		if d.state != stateFlying && d.state != stateHoverFailsafe {
			ack.Reason = "velocity changes require FLYING or HOVER_FAILSAFE state"
			return ack
		}

		// A fresh velocity command explicitly resumes teleoperation.
		d.state = stateFlying
		d.failsafeReason = ""
		d.velocity = command.Velocity

		sentAt := command.SentAt
		d.lastVelocityAt = &sentAt
		d.lastVelocityReceivedAt = &now

	case "land":
		if d.state != stateFlying && d.state != stateHoverFailsafe {
			ack.Reason = "landing requires FLYING state"
			return ack
		}
		d.state = stateLanding
		d.velocity = velocity{}

	case "return_home":
		if d.state != stateFlying {
			ack.Reason = "return home requires FLYING state"
			return ack
		}
		// This simulator has no map or mission planner yet.
		// For now, model return-home as an immediate hover.
		d.velocity = velocity{}

	default:
		ack.Reason = "unknown command action"
		return ack
	}

	ack.Accepted = true
	d.lastCommandAt = &now
	ack.State = d.state
	return ack
}

func (d *drone) enforceVelocityFailsafe(now time.Time) bool {
	d.mu.Lock()
	defer d.mu.Unlock()

	isMoving := d.velocity.Forward != 0 ||
		d.velocity.Right != 0 ||
		d.velocity.Up != 0

	if d.state != stateFlying ||
		!isMoving ||
		d.lastVelocityReceivedAt == nil ||
		now.Sub(*d.lastVelocityReceivedAt) <= velocityFailsafeTimeout {
		return false
	}

	d.velocity = velocity{}
	d.state = stateHoverFailsafe
	d.failsafeReason = "no new velocity command received in at least 500 ms"

	return true
}

func (d *drone) getTelemetry() telemetry {
	d.mu.Lock()
	defer d.mu.Unlock()

	now := time.Now()
	elapsed := 0.0
	if !d.lastTelemetryAt.IsZero() {
		elapsed = now.Sub(d.lastTelemetryAt).Seconds()
	}
	d.lastTelemetryAt = now

	// Simulate a very small battery drain while the agent is running.
	d.batteryPct = max(0, d.batteryPct-0.01)

	// Simulate vertical motion while flying.
	if d.state == stateFlying {
		d.altitudeM = max(0, d.altitudeM+d.velocity.Up*elapsed)

		if d.altitudeM == 0 && d.velocity.Up < 0 {
			d.velocity.Up = 0
		}
	}

	// Simulate descent while landing.
	if d.state == stateLanding {
		d.altitudeM = max(0, d.altitudeM-1)
		if d.altitudeM == 0 {
			d.state = stateDisarmed
		}
	}

	return telemetry{
		Type:           "telemetry",
		State:          d.state,
		BatteryPct:     d.batteryPct,
		AltitudeM:      d.altitudeM,
		Velocity:       d.velocity,
		FailsafeReason: d.failsafeReason,
		LastCommandAt:  d.lastCommandAt,
		SentAt:         now,
	}
}

func main() {
	apiKey := requiredEnv("LIVEKIT_API_KEY")
	apiSecret := requiredEnv("LIVEKIT_API_SECRET")
	liveKitURL := requiredEnv("LIVEKIT_URL")

	simulatedDrone := newDrone()
	var room *lksdk.Room

	callbacks := lksdk.NewRoomCallback()
	callbacks.OnDataPacket = func(packet lksdk.DataPacket, params lksdk.DataReceiveParams) {
		userData, ok := packet.(*lksdk.UserDataPacket)
		if !ok {
			return
		}

		var command command
		if err := json.Unmarshal(userData.Payload, &command); err != nil {
			log.Printf("invalid command from %s: %v", params.SenderIdentity, err)
			return
		}

		if command.Type != "command" {
			return
		}

		if !strings.HasPrefix(params.SenderIdentity, operatorIdentity) {
			log.Printf("ignoring command from unauthorized sender %s", params.SenderIdentity)
			return
		}

		log.Printf(
			"command received from %s: id=%s action=%s",
			params.SenderIdentity,
			command.ID,
			command.Action,
		)

		ack := simulatedDrone.apply(command)
		if err := publishJSON(room.LocalParticipant, ack, true); err != nil {
			log.Printf("publishing acknowledgement: %v", err)
		}
	}

	var err error
	room, err = lksdk.ConnectToRoom(
		liveKitURL,
		lksdk.ConnectInfo{
			APIKey:              apiKey,
			APISecret:           apiSecret,
			RoomName:            roomName,
			ParticipantIdentity: agentIdentity,
		},
		callbacks,
	)
	if err != nil {
		log.Fatal(err)
	}
	defer room.Disconnect()

	log.Printf("joined room %q as %q", roomName, agentIdentity)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	telemetryTicker := time.NewTicker(time.Second)
	defer telemetryTicker.Stop()

	failsafeTicker := time.NewTicker(100 * time.Millisecond)
	defer failsafeTicker.Stop()

	for {
		select {
		case <-ctx.Done():
			log.Println("drone agent shutting down")
			return

		case <-failsafeTicker.C:
			if simulatedDrone.enforceVelocityFailsafe(time.Now()) {
				log.Println("velocity failsafe activated: entering HOVER_FAILSAFE")
			}

		case <-telemetryTicker.C:
			currentTelemetry := simulatedDrone.getTelemetry()

			// Telemetry is intentionally lossy: a fresh update arrives every second.
			if err := publishJSON(room.LocalParticipant, currentTelemetry, false); err != nil {
				log.Printf("publishing telemetry: %v", err)
			}
		}
	}
}

func publishJSON(
	participant *lksdk.LocalParticipant,
	message any,
	reliable bool,
) error {
	payload, err := json.Marshal(message)
	if err != nil {
		return err
	}

	options := []lksdk.DataPublishOption{
		lksdk.WithDataPublishReliable(reliable),
	}

	return participant.PublishDataPacket(lksdk.UserData(payload), options...)
}

func requiredEnv(name string) string {
	value := os.Getenv(name)
	if value == "" {
		log.Fatalf("%s must be set", name)
	}
	return value
}
