# End-to-end Stream Health Monitor

# - A cloud service monitors many drone video streams. It receives events indicating when each stream connects, receives a video frame, or disconnects.
# - Write class that tracks each stream’s status and identifies streams whose video is not currently arriving.
# - Event types: 'connected, frame_received, disconnected'

# Each event looks like:
# {
#     "event_id": "evt-1",
#     "stream_id": "drone-1",
#     "type": "connected",
#     "timestamp": 100, <--- seconds
# }

# Each stream has status:
# WAITING_FOR_FRAME: Connected, but no frame has arrived yet. Still within timeout.
# HEALTHY: Connected, and a frame has arrived recently enough.
# STALLED: Connected, but no frame arrived yet. Elapsed time >= timeout.
# DISCONNECTED: The latest connection state is disconnected.
# UNKNOWN: No accepted events exist for this stream.

# get_status(stream_id, now):
# If the stream doesn’t exist, return "UNKNOWN".
# If disconnected, return "DISCONNECTED".
# If connected, decide which timestamp to measure from:
# - Use last_frame_at if a frame has arrived.
# - Otherwise, use connected_at.

# If now - starting_ts >= self.timeout, return "STALLED".
# Otherwise:
# - If a frame has arrived, return "HEALTHY".
# - ELSE return "WAITING_FOR_FRAME".


# For connected stream:
# - If at least 1 frame has arrived during current connection, measure from the latest frame.
# - If no frame has arrived during current connection, measure from connection time.

# Event-processing rules:
# 1. Dedup: If an event_id has already been accepted, ignore any duplicates.
# 2. Ordering: For each stream, ignore an event whose timestamp < latest accepted event for that stream. (Events sometimes do NOT arrive in chronological order.)
# 3. Equal timestamps: Process events with equal timestamps in order they arrive.
# 4. Connect: A 'connected' event starts a new connection and resets the last-frame timestamp.
# 5. Frame: Accept 'frame_received' only while stream is connected.
# 6. Disconnect: A 'disconnected' event disconnects the stream. A later 'connected' event starts new connection.
# 7. Recovery: A fresh frame received while stream is 'STALLED' makes it 'HEALTHY' again.
# 8. Invalid events: Raise ValueError for an unsupported event type or missing required field.

# To answer “Is this stream healthy now?” we just must know:
# 1. Is it connected?
# 2. When current connection began
# 3. When its latest frame arrived
# 4. Latest accepted event timestamp.

# use each dictionary value to store each stream’s current state, not a list of every event:
# self.streams = {
#     "drone-1": {
#         "connected": True,
#         "connected_at": 100,
#         "last_frame_at": 105,
#         "last_event_at": 105,
#     }
# }

# Before coding, ask only questions that change the design:
# “Can events arrive out of order or more than once?”
# “Do we need to keep historical events, or only current state?”
# “What scale should I optimize for?”
# “Should I treat timestamps as reliable and monotonic?”
# “What should happen with invalid or unknown stream IDs?”

# Say your plan before writing:
# “I’ll start with a dictionary keyed by stream ID so each update and lookup is O(1).
# I’ll make the simple behavior correct first, then add handling for duplicates and stale events if that is in scope.”

class StreamHealthMonitor:
    """Processes each drone's stream events, tracks each stream’s status, and
    IDs streams whose video is not now arriving."""
    def __init__(self, frame_timeout_secs):
        """Create monitor with positive frame timeout."""
        if frame_timeout_secs <= 0:
            raise ValueError('Timeout must be positive')
        self.timeout = frame_timeout_secs
        self.streams = {}
        self.processed_event_ids = set()

    def process_event(self, event):
        """Update stream's state based on one event."""
        event_id = event["event_id"]
        stream_id = event["stream_id"]
        event_type = event["type"]
        ts = event["timestamp"]

        if event_type not in ["connected", "frame_received", "disconnected"]:
            raise ValueError('got invalid event type')

        # dedup event_id
        if event_id in self.processed_event_ids:
            print(f"ignoring event {event_id}. already processed.")
            return

        stream = self.streams.get(stream_id)  # get() returns None if stream_id not in streams

        # ignores event with older timestamp than last accepted event
        if stream and ts < stream['last_event_at']:
            print(f"ignoring event with older timestamp {ts}")
            return

        match event_type:
            # starts new connection and resets last-frame timestamp.
            case 'connected':
                self.streams[stream_id] = {
                    'connected': True,
                    'connected_at': ts,
                    'last_frame_at': None,  # 'connected' does NOT mean frame was received
                    'last_event_at': ts
                }
            # Accept 'frame_received' only while stream is connected.
            case 'frame_received':
                if stream and stream['connected']:
                    stream['last_frame_at'] = ts
                    stream['last_event_at'] = ts
                else:
                    print("ignoring 'frame_received' event since stream NOT connected")
                    return
            case 'disconnected':
                if stream:
                    stream['connected'] = False
                    stream['last_event_at'] = ts
                else:
                    print("ignoring 'disconnected' event since stream doesn't exist")
                    return

        self.processed_event_ids.add(event_id)

    def get_status(self, stream_id, now):
        """Return stream's current status at time 'now'."""
        stream = self.streams.get(stream_id)

        if stream is None:
            return 'UNKNOWN'

        if not stream['connected']:
            return 'DISCONNECTED'

        # Don't use "stream['last_frame_at']", since 'last_frame_at' could be 0, and 'if 0' is False.
        frame_arrived = stream['last_frame_at'] is not None

        # Find starting timestamp:
        # If a frame arrived, return last_frame_at timestamp,
        # else return connected_at timestamp.
        starting_ts = stream['last_frame_at'] if frame_arrived else stream['connected_at']

        if now - starting_ts >= self.timeout:
            return 'STALLED'

        # Has not timed out
        if frame_arrived:
            return 'HEALTHY'
        else:
            return 'WAITING_FOR_FRAME'

    def get_streams_needing_attention(self, now):
        """Return IDs for streams with status STALLED or DISCONNECTED."""
        ids = []
        for stream_id in self.streams:  # loops thru only keys of map
            if self.get_status(stream_id, now) in ['STALLED', 'DISCONNECTED']:
                ids.append(stream_id)

        return ids

if __name__ == "__main__":
    try:
        m = StreamHealthMonitor(-5)
        assert False, "ValueError not raised"
    except ValueError as e:
        assert str(e) == 'Timeout must be positive'

    m = StreamHealthMonitor(10)

    try:
        m.process_event({
            "event_id": "bad-1",
            "stream_id": "drone-2",
            "type": "teleported",
            "timestamp": 50,
        })
        assert False, 'ValueError not raised'
    except ValueError as e:
        assert 'got invalid event type' in str(e)

    # Connect drone's stream
    m.process_event({
        "event_id": "e1",
        "stream_id": "drone-1",
        "type": "connected",
        "timestamp": 100,
    })
    assert m.streams["drone-1"]["connected"] is True
    assert m.streams["drone-1"]["connected_at"] == 100
    assert m.streams["drone-1"]["last_frame_at"] is None
    assert "e1" in m.processed_event_ids

    # Check it ignores event with older timestamp
    m.process_event({
        "event_id": "e2",
        "stream_id": "drone-1",
        "type": "disconnected",
        "timestamp": 90,
    })
    assert m.streams["drone-1"]["connected_at"] == 100
    assert 'e2' not in m.processed_event_ids

    # Accept frame for the connected stream.
    m.process_event({
        "event_id": "e3",
        "stream_id": "drone-1",
        "type": "frame_received",
        "timestamp": 105,
    })
    assert m.streams["drone-1"]["last_frame_at"] == 105
    assert m.streams["drone-1"]["last_event_at"] == 105
    assert "e3" in m.processed_event_ids

    # Ignore frame for a stream that has never connected.
    m.process_event({
        "event_id": "e4",
        "stream_id": "unknown-drone",
        "type": "frame_received",
        "timestamp": 106,
    })
    assert "unknown-drone" not in m.streams
    assert "e4" not in m.processed_event_ids

    # Ignore event for older frame
    m.process_event({
        "event_id": "e5",
        "stream_id": "drone-1",
        "type": "frame_received",
        "timestamp": 103,
    })
    assert m.streams["drone-1"]["last_frame_at"] == 105
    assert "e5" not in m.processed_event_ids

    # Disconnect drone's stream
    m.process_event({
        "event_id": "e6",
        "stream_id": "drone-1",
        "type": "disconnected",
        "timestamp": 109,
    })
    assert m.streams["drone-1"]["connected"] is False
    assert m.streams["drone-1"]["last_event_at"] == 109

    #---------- Create fresh monitor ----------
    m = StreamHealthMonitor(10)
    # with no events, stream doesn't yet exist in memory
    assert m.get_status('drone-2', 100) == 'UNKNOWN'

    m.process_event({
        'event_id': 's1',
        'stream_id': 'drone-2',
        'type': 'connected',
        'timestamp': 100,
    })
    assert m.get_status('drone-2', 109) == 'WAITING_FOR_FRAME'
    assert not m.get_streams_needing_attention(109)
    assert m.get_status('drone-2', 110) == 'STALLED'
    assert m.get_streams_needing_attention(110) == ['drone-2']
    m.process_event({
        'event_id': 's2',
        'stream_id': 'drone-2',
        'type': 'frame_received',
        'timestamp': 112,
    })
    assert m.get_status('drone-2', 112) == 'HEALTHY'
    assert m.get_status('drone-2', 121) == 'HEALTHY'
    assert not m.get_streams_needing_attention(121)
    assert m.get_status('drone-2', 122) == 'STALLED'
    assert m.get_streams_needing_attention(122) == ['drone-2']
    m.process_event({
        'event_id': 's3',
        'stream_id': 'drone-2',
        'type': 'frame_received',
        'timestamp': 123,
    })
    assert m.get_status('drone-2', 123) == 'HEALTHY'

    m.process_event({
        'event_id': 't1',
        'stream_id': 'drone-3',
        'type': 'connected',
        'timestamp': 124,
    })
    assert m.get_status('drone-2', 133) == 'STALLED'
    assert m.get_streams_needing_attention(133) == ['drone-2']
    assert m.get_status('drone-3', 134) == 'STALLED'
    assert m.get_streams_needing_attention(134) == ['drone-2', 'drone-3']
    m.process_event({
        'event_id': 't2',
        'stream_id': 'drone-2',
        'type': 'frame_received',
        'timestamp': 138,
    })
    assert m.get_status('drone-2', 138) == 'HEALTHY'
    assert m.get_status('drone-3', 138) == 'STALLED'
    assert m.get_streams_needing_attention(138) == ['drone-3']
    m.process_event({
        'event_id': 't3',
        'stream_id': 'drone-3',
        'type': 'frame_received',
        'timestamp': 139,
    })
    assert m.get_status('drone-3', 140) == 'HEALTHY'
    assert not m.get_streams_needing_attention(140)
    m.process_event({
        'event_id': 't4',
        'stream_id': 'drone-2',
        'type': 'disconnected',
        'timestamp': 141,
    })
    assert m.get_status('drone-2', 141) == 'DISCONNECTED'
    assert m.get_streams_needing_attention(141) == ['drone-2']
    m.process_event({
        'event_id': 't5',
        'stream_id': 'drone-3',
        'type': 'disconnected',
        'timestamp': 142,
    })
    assert m.get_status('drone-3', 142) == 'DISCONNECTED'
    assert m.get_streams_needing_attention(142) == ['drone-2', 'drone-3']
    print("All tests passed!")
