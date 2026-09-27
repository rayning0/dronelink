package main

import (
	"fmt"
	"net/http"
)

func main() {
	// Register the health check endpoint
	http.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		w.Write([]byte("ok"))
		// w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		// w.WriteHeader(http.StatusOK)
		// fmt.Fprint(w, "ok")
	})

	// Start server
	fmt.Println("Server starting on :8080...")
	if err := http.ListenAndServe(":8080", nil); err != nil {
		fmt.Printf("Server failed to start: %v\n", err)
	}
}
