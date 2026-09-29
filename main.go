package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/livekit/protocol/auth"
)

type tokenRequest struct {
	Room     string `json:"room"`
	Identity string `json:"identity"`
	Role     string `json:"role"`
}

type tokenResponse struct {
	Token string `json:"token"`
}

func main() {
	apiKey := requiredEnv("LIVEKIT_API_KEY")
	apiSecret := requiredEnv("LIVEKIT_API_SECRET")

	mux := http.NewServeMux()

	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})

	mux.HandleFunc("POST /token", func(w http.ResponseWriter, r *http.Request) {
		var request tokenRequest

		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			http.Error(w, "invalid JSON request body", http.StatusBadRequest)
			return
		}

		if request.Room == "" || request.Identity == "" || request.Role == "" {
			http.Error(w, "room, identity, and role are required", http.StatusBadRequest)
			return
		}

		grant := &auth.VideoGrant{
			RoomJoin:     true,
			Room:         request.Room,
			CanSubscribe: boolPtr(true),
		}

		switch request.Role {
		case "operator":
			// Operator can view video and send control/telemetry data,
			// but cannot publish a camera track.
			grant.CanPublish = boolPtr(false)
			grant.CanPublishData = boolPtr(true)

		case "drone-camera":
			// Simulated drone can publish video and exchange data.
			grant.CanPublish = boolPtr(true)
			grant.CanPublishData = boolPtr(true)

		case "drone-agent":
			// Go drone agent will exchange commands and telemetry,
			// but does not publish a camera track.
			grant.CanPublish = boolPtr(false)
			grant.CanPublishData = boolPtr(true)

		default:
			http.Error(w, "role may only be operator, drone-camera, or drone-agent", http.StatusBadRequest)
			return
		}

		accessToken := auth.NewAccessToken(apiKey, apiSecret).
			SetIdentity(request.Identity).
			SetVideoGrant(grant).
			SetValidFor(time.Hour)

		token, err := accessToken.ToJWT()
		if err != nil {
			log.Printf("creating token: %v", err)
			http.Error(w, "could not create token", http.StatusInternalServerError)
			return
		}

		writeJSON(w, http.StatusOK, tokenResponse{Token: token})
	})

	mux.Handle("/img/", http.StripPrefix("/img/", http.FileServer(http.Dir("img"))))
	mux.Handle("/", http.FileServer(http.Dir("web")))

	log.Println("control plane listening on http://127.0.0.1:8080")
	log.Fatal(http.ListenAndServe(":8080", mux))
}

func requiredEnv(name string) string {
	value := os.Getenv(name)
	if value == "" {
		log.Fatalf("%s must be set", name)
	}
	return value
}

func boolPtr(value bool) *bool {
	return &value
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)

	if err := json.NewEncoder(w).Encode(value); err != nil {
		log.Printf("writing JSON response: %v", err)
	}
}
