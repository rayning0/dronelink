# A cloud video publisher (like Skydio Cloud) begins publishing a video track.
# The LiveKit server creates a pending track while waiting for that track’s first RTP/media packet.

# A pending track consumes limited server capacity.
# If the publisher abandons the attempt and media never arrives, the pending track must eventually be cleaned up;
# otherwise, future valid publishing attempts can be rejected.

# “Use separate pending and active collections, because only tracks waiting for their first media packet consume this limited resource. Clean up pending tracks through both an explicit cancel path and a timeout path, since distributed systems cannot assume cancellation messages always arrive.”

class PendingTrackRegistry:
    def __init__(self, max_pending_tracks, pending_timeout):
        if max_pending_tracks <= 0 or pending_timeout <= 0:
            raise ValueError('Both max_pending_tracks and pending_timeout must be positive')
        # track_id: start timestamp, or time track began to publish.
        self.pending = {}   # Ex: "camera-1: 100"

        self.active = set()
        self.max_pending_tracks = max_pending_tracks
        self.pending_timeout = pending_timeout  # in seconds

    def start_publish(self, track_id, now):
        """Create a pending track."""
        self.expire_pending(now)

        # Don't do "if track_id in [self.pending, self.active]:"
        # This wrongly checks if track_id == self.pending or self.active
        # Instead of just comparing to their keys.
        if track_id in self.pending or track_id in self.active:
            raise ValueError(f"Track {track_id} is already pending or active.")

        if len(self.pending) >= self.max_pending_tracks:
            raise RuntimeError(f"Track {track_id} exceeds max allowed {self.max_pending_tracks} pending tracks.")

        self.pending[track_id] = now

    def receive_first_packet(self, track_id, now):
        """Move a pending track to active after its first media packet."""
        self.expire_pending(now)
        if track_id not in self.pending:
            return False

        del self.pending[track_id]
        self.active.add(track_id)
        return True

    # systems must still have timeout cleanup in case this cancellation never arrives.
    def cancel_publish(self, track_id):
        """Explicitly remove a pending track when the publisher cancels."""
        if track_id in self.pending:
            del self.pending[track_id]
            return True

        return False

    def expire_pending(self, now):
        """Remove timed-out pending tracks and return their IDs."""
        expired_ids = []

        # Can't use "for track_id, start_ts in self.pending.items():"
        # If you delete entries in loop. Will get
        # "RuntimeError: dictionary changed size during iteration".
        # Instead, use list(self.pending.items()). It makes shallow copy,
        # different from self.pending. It lets you delete items from self.pending.
        for track_id, start_ts in list(self.pending.items()):
            if now - start_ts >= self.pending_timeout:
                expired_ids.append(track_id)
                del self.pending[track_id]

        return expired_ids

    def stop_track(self, track_id):
        """Remove an active track when publishing ends."""
        if track_id in self.active:
            self.active.remove(track_id)
            return True

        return False

    def close_participant(self):
        """Remove every pending and active track for this participant."""
        self.pending = {}
        self.active = set()

if __name__ == '__main__':
    try:
        p = PendingTrackRegistry(0, 10)
    except ValueError as e:
        assert str(e) == 'Both max_pending_tracks and pending_timeout must be positive'

    p = PendingTrackRegistry(2, 10)
    p.start_publish('camera-1', 100)
    assert p.pending['camera-1'] == 100

    p.start_publish('camera-2', 101)
    try:
        p.start_publish('camera-3', 102)
    except RuntimeError as e:
        assert str(e) == "Track camera-3 exceeds max allowed 2 pending tracks."

    try:
        p.start_publish('camera-1', 103)
    except ValueError as e:
        assert str(e) == "Track camera-1 is already pending or active."

    # At timeout (10 secs) for camera-1,
    # start_publish() deletes expired camera-1 from pending tracks.
    p.start_publish('camera-4', 110)
    assert p.pending == {'camera-2': 101, 'camera-4': 110}

    # camera-5 not in pending
    assert p.receive_first_packet('camera-5', 111) is False
    # camera-2 just expired and got deleted from pending
    assert p.receive_first_packet('camera-2', 111) is False

    # camera-4 gets first packet before timeout,
    # so it moves from 'pending' to 'active'
    assert p.receive_first_packet('camera-4', 112) is True
    assert not p.pending
    assert p.active == {'camera-4'}
    assert p.receive_first_packet('camera-4', 113) is False

    # cancel_publish deletes a pending track
    p.start_publish('camera-5', 114)
    p.start_publish('camera-6', 115)
    assert p.cancel_publish('camera-5') is True
    assert p.pending == {'camera-6': 115}
    assert p.cancel_publish('camera-4') is False

    # stop_track removes an active track
    assert p.stop_track('camera-4') is True
    assert p.stop_track('camera-6') is False
    assert not p.active

    # close_participant() deletes all pending and active tracks
    assert p.receive_first_packet('camera-6', 120) is True
    assert p.active == {'camera-6'}
    p.start_publish('camera-7', 121)
    assert p.pending == {'camera-7': 121}
    p.close_participant()
    assert not p.active and not p.pending

    # expire_pending() itself behaves correctly one second before and exactly at the timeout boundary.
    p = PendingTrackRegistry(1, 10)
    p.start_publish("camera-1", 100)

    assert not p.expire_pending(109)
    assert len(p.pending) == 1

    assert p.expire_pending(110) == ["camera-1"]
    assert len(p.pending) == 0
    print("All tests passed!")

# Kevin's PR bug: https://github.com/livekit/livekit/issues/4970
# 1. Connect one long-lived Go SDK participant to a LiveKit room.
# 2. Repeat 20 times:
#    - PublishTrack(new local track)
#    - Write no media samples / no RTP packets
#    - UnpublishTrack(track)
# 3. Try PublishTrack one more time. The 21st attempt fails because the server still believes it has 20 pending tracks.

# AddTrack
# → server creates pending-track entry
# → no first RTP packet ever arrives
# → client calls UnpublishTrack
# → server does not clear pending entry
# → repeat 20 times
# → future publishing blocked

# What if the client thinks it unpublished a track,
# but the server never gets a usable cancellation signal?

# "I prefer explicit server-side cancellation, but I'd still keep timeout cleanup since a client can crash, disconnect, or fail to communicate cancellation. Also consider late-message handling if a released track’s media could be mistaken for a new track."

# Imagine a drone is flying over a site.
# 1. The drone’s hardware encoder produces H.265 video.
# 2. Video crosses the drone’s cellular/Wi-Fi links and arrives at a Skydio cloud ingest node (Skydio Cloud).
# 3. That cloud service connects to the relevant LiveKit room as a participant—something like: drone-cloud-publisher-123
# 4. The service tells LiveKit: “I am going to publish a new camera track.”
# 5. LiveKit creates a pending track entry. It reserves a small piece of track/session state while waiting for the first RTP video packet.
# 6. The ingest node starts forwarding video packets into that track.
# 7. When LiveKit receives the first packet, it moves the track: PENDING → ACTIVE
# 8. The SFU can now forward that active camera track to the operator’s browser.

# Where failure happens

# Suppose the ingest node starts the publishing process, but the drone’s video never reaches it.
# Possible reasons:
# - The drone temporarily loses its cellular link.
# - The camera encoder crashes or is restarting.
# - An H.265-to-H.264 fallback fails before the first H.264 frame appears.
# - The ingest node cancels the attempt because its upstream video source vanished.
# - A network or SDK error interrupts publishing before the first RTP packet.

# The publisher may then say: “Never mind, stop publishing that track.”

# But the server may not receive a meaningful cancellation signal for its pending-track bookkeeping. It is still waiting for a first media packet that will never arrive. LiveKit pending slots pile up.

# If every failed attempt leaves a pending slot behind, eventually the participant reaches the pending-track limit. Then even after the drone’s connectivity recovers and good video is available, LiveKit rejects the new publish attempt.

# The operator sees: Drone is online, but no video appears.
#_______________________________

# LiveKit's PR fix: https://github.com/livekit/livekit/pull/4998
# It adds 2 protections:
# 1. Clean up abandoned pending video publishes when capacity is full.
# 2. Prevent late packets from an abandoned publish being attached to the wrong new track.

# Before PR:
# 1. AddTrack(camera-A)
# 2. Server reserves pending slot.
# 3. No RTP arrives.
# 4. SDK UnpublishTrack removes local sender.
# 5. Server never learns that the pending reservation is abandoned.
# 6. Repeat 20 times.
# 7. Server rejects every future AddTrack.

# After PR:
# 1. Twenty abandoned pending tracks accumulate.
# 2. Client calls AddTrack(camera-new).
# 3. Server is at capacity.
# 4. Server finds pending tracks that have waited over 30 seconds without media.
# 5. Server releases them and emits TrackUnpublished.
# 6. Server accepts camera-new.
# 7. If old camera-A media appears late, server drops it rather than attaching it to camera-new.

# In more detail, what LiveKit PR does:
# 1. A client calls `AddTrack`; LiveKit creates a pending media-track entry while waiting for RTP.
# 2. Before PR #4998, if the client abandoned that publish before RTP arrived, the pending entry remained.
# 3. Repeating this could fill LiveKit’s 20 pending-track limit.
# 4. Future `AddTrack` requests were then rejected until the participant left the room.
# 5. The PR adds timeout detection through `ParticipantSupervisor`.
# 6. A pending, unmuted publication that has not produced media for about 30 seconds is considered timed out.
# 7. When a new `AddTrack` arrives at the pending-track limit, LiveKit finds timed-out pending tracks.
# 8. It removes those entries, removes their supervisor monitors, and signals `TrackUnpublished` to capable clients.
# 9. If this creates capacity, LiveKit accepts the new publish request.
# 10. If no pending tracks have timed out, it still rejects the new request normally.
# 11. Removing an old pending track creates a new risk: delayed RTP from it could arrive later.
# 12. The PR stores the released track’s client, codec, and SDP IDs in a bounded tombstone list.
# 13. If late media or an SDP offer matches a tombstoned ID, LiveKit drops it.
# 14. This prevents old media from being attached to another pending video track of the same type.
# 15. If the client explicitly submits a new `AddTrack` that reuses one of those IDs, LiveKit clears that tombstone group.
# 16. Media for that newly requested publication can then flow normally.
