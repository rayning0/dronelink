# Sustained Stream Quality Classifier

# A cloud service gets periodic WebRTC-style quality samples from many drone video streams. 1 poor measurement should not trigger an alert, since cellular/Wi‑Fi conditions can briefly fluctuate.

# Build a monitor that classifies each stream as:
# UNKNOWN
# HEALTHY
# DEGRADED
# FAILED

# It should only mark a stream degraded or failed after sustained bad quality and only restore it after sustained good quality.

# sample =
# {
#     "sample_id": "sample-1",
#     "stream_id": "drone-1",
#     "timestamp": 100,
#     "rtt_ms": 85,
#     "packet_loss_pct": 1.2,
#     "jitter_ms": 8,
#     "bitrate_kbps": 1500,
#     "frames_decoded": 300,
# }

# - Samples for a stream normally arrive once per second.
# - frames_decoded is a cumulative counter from the browser.
# - Assume every sample has the required fields and valid numeric values.
# - A sample with the same sample_id is a duplicate and should be ignored.
# - Ignore all older samples (timestamp < latest accepted sample) for that stream
# - Samples with equal timestamps are processed in arrival order.

# A sample is BAD if any of these is true:

# packet_loss_pct >= 10
# jitter_ms >= 50
# rtt_ms >= 500
# bitrate_kbps < 250
# frames_decoded did not increase since last accepted sample for that stream.

# <State-Transition Rules:>

# Start every unseen stream as: UNKNOWN

# After its first accepted sample:
# good sample → HEALTHY
# bad sample  → HEALTHY

# | Condition                                            | New status |
# | 3 consecutive bad samples                            | `DEGRADED` |
# | 5 consecutive bad samples                            | `FAILED`   |
# | 2 consecutive good samples after `DEGRADED`/`FAILED` | `HEALTHY`  |

# A good sample resets consecutive_bad count to 0.
# A bad sample resets consecutive_good count to 0.
# While DEGRADED or FAILED, 1 good sample is not enough to restore health.
# A new bad sample after recovery starts a fresh bad-sample count.

# self.streams[stream_id] = {
#     'status': 'HEALTHY',
#     'last_timestamp': 100,
#     'last_frames_decoded': 300,
#     'consecutive_bad': 0,
#     'consecutive_good': 1,
# }

class StreamQualityMonitor:
    def __init__(self):
        self.streams = {}
        self.sample_ids = set()

    def process_sample(self, sample):
        """Accept 1 quality sample and update its stream's state."""
        sample_id = sample['sample_id']
        stream_id = sample['stream_id']
        ts = sample['timestamp']
        rtt = sample['rtt_ms']
        ploss = sample['packet_loss_pct']
        jitter = sample['jitter_ms']
        bitrate = sample['bitrate_kbps']
        frames_decoded = sample['frames_decoded']

        stream = self.streams.get(stream_id)

        if sample_id in self.sample_ids:
            print(f"Ignoring duplicate sample ID: {sample_id}. Already processed.")
            return
        if stream and ts < stream['last_timestamp']:
            print(f"Ignoring older event with timestamp {ts}")
            return

        # False is GOOD sample. True is BAD sample.
        frame_no_progress = False
        if stream:
            frame_no_progress = frames_decoded <= stream['last_frames_decoded']

        is_bad = any([
            ploss >= 10,
            jitter >= 50,
            rtt >= 500,
            bitrate < 250,
            frame_no_progress
        ])

        if stream:
            stream['last_timestamp'] = ts
            stream['last_frames_decoded'] = frames_decoded
            if is_bad:
                stream['consecutive_bad'] += 1
                stream['consecutive_good'] = 0
            else:
                stream['consecutive_good'] += 1
                stream['consecutive_bad'] = 0

            if stream['consecutive_bad'] >= 3:
                stream['status'] = 'DEGRADED'
            if stream['consecutive_bad'] >= 5:
                stream['status'] = 'FAILED'
            if stream['status'] in ['DEGRADED', 'FAILED'] and stream['consecutive_good'] >= 2:
                stream['status'] = 'HEALTHY'
        else:
            self.streams[stream_id] = {
                'status': 'HEALTHY',
                'last_timestamp': ts,
                'last_frames_decoded': frames_decoded,
                'consecutive_bad': 1 if is_bad else 0,
                'consecutive_good': 0 if is_bad else 1,
            }

        self.sample_ids.add(sample_id)

    def get_status(self, stream_id):
        """Return UNKNOWN, HEALTHY, DEGRADED, or FAILED."""
        stream = self.streams.get(stream_id)

        if stream is None:
            return 'UNKNOWN'

        return stream['status']

    def get_streams_needing_attention(self):
        """Return stream IDs whose status is DEGRADED or FAILED."""
        ids = []
        for stream_id, stream in self.streams.items():
            if stream['status'] in ['DEGRADED', 'FAILED']:
                ids.append(stream_id)

        return ids

if __name__ == '__main__':
    m = StreamQualityMonitor()
    assert m.get_status('unknown_id') == 'UNKNOWN'

    m.process_sample({
        "sample_id": "sample-1",
        "stream_id": "drone-1",
        "timestamp": 100,
        "rtt_ms": 85,
        "packet_loss_pct": 1.2,
        "jitter_ms": 8,
        "bitrate_kbps": 1500,
        "frames_decoded": 300,
    })
    # First good sample makes stream HEALTHY
    assert m.get_status('drone-1') == 'HEALTHY'

    m.process_sample({
        "sample_id": "sample-1",  # Repeats sample ID: Ignores sample.
        "stream_id": "drone-1",
        "timestamp": 100,
        "rtt_ms": 85,
        "packet_loss_pct": 1.2,
        "jitter_ms": 8,
        "bitrate_kbps": 1500,
        "frames_decoded": 300,
    })
    m.process_sample({
        "sample_id": "sample-0",
        "stream_id": "drone-1",
        "timestamp": 99,          # Timestamp older than last one. Ignores sample.
        "rtt_ms": 85,
        "packet_loss_pct": 1.2,
        "jitter_ms": 8,
        "bitrate_kbps": 1500,
        "frames_decoded": 300,
    })

    m.process_sample({
        "sample_id": "sample-2",
        "stream_id": "drone-1",
        "timestamp": 100,
        "rtt_ms": 85,
        "packet_loss_pct": 1.2,
        "jitter_ms": 8,
        "bitrate_kbps": 1500,
        "frames_decoded": 300,  # did not increase since last sample, so it's BAD
    })
    # 1 bad sample: stream stays HEALTHY
    assert m.get_status('drone-1') == 'HEALTHY'

    m.process_sample({
        "sample_id": "sample-3",
        "stream_id": "drone-1",
        "timestamp": 105,
        "rtt_ms": 85,
        "packet_loss_pct": 10,  # BAD
        "jitter_ms": 8,
        "bitrate_kbps": 1500,
        "frames_decoded": 350,
    })
    m.process_sample({
        "sample_id": "sample-4",
        "stream_id": "drone-1",
        "timestamp": 110,
        "rtt_ms": 85,
        "packet_loss_pct": 1.2,
        "jitter_ms": 50,        # BAD
        "bitrate_kbps": 1500,
        "frames_decoded": 400,
    })
    # 3 consecutive bad samples: 'DEGRADED'
    assert m.get_status('drone-1') == 'DEGRADED'

    m.process_sample({
        "sample_id": "sample-5",
        "stream_id": "drone-1",
        "timestamp": 115,
        "rtt_ms": 500,          # BAD
        "packet_loss_pct": 1.2,
        "jitter_ms": 8,
        "bitrate_kbps": 1500,
        "frames_decoded": 450,
    })
    m.process_sample({
        "sample_id": "sample-6",
        "stream_id": "drone-1",
        "timestamp": 120,
        "rtt_ms": 85,
        "packet_loss_pct": 1.2,
        "jitter_ms": 8,
        "bitrate_kbps": 249,    # BAD
        "frames_decoded": 500,
    })
    # 5 consecutive bad samples: 'FAILED'
    assert m.get_status('drone-1') == 'FAILED'

    m.process_sample({
        "sample_id": "sample-7",
        "stream_id": "drone-1",
        "timestamp": 125,
        "rtt_ms": 85,
        "packet_loss_pct": 1.2,
        "jitter_ms": 8,
        "bitrate_kbps": 1500,
        "frames_decoded": 550,
    })
    # 1 good sample after 'FAILED' is still 'FAILED' status
    assert m.get_status('drone-1') == 'FAILED'

    m.process_sample({
        "sample_id": "sample-8",
        "stream_id": "drone-2",     # new drone 2
        "timestamp": 100,
        "rtt_ms": 85,
        "packet_loss_pct": 10,      # BAD sample
        "jitter_ms": 8,
        "bitrate_kbps": 1500,
        "frames_decoded": 300,
    })
    # 1 bad sample for new drone 2 is still HEALTHY
    assert m.get_status('drone-2') == 'HEALTHY'
    m.process_sample({
        "sample_id": "sample-9",
        "stream_id": "drone-2",     # new drone 2
        "timestamp": 105,
        "rtt_ms": 85,
        "packet_loss_pct": 10,      # BAD sample
        "jitter_ms": 8,
        "bitrate_kbps": 1500,
        "frames_decoded": 350,
    })
    m.process_sample({
        "sample_id": "sample-10",
        "stream_id": "drone-2",     # new drone 2
        "timestamp": 110,
        "rtt_ms": 85,
        "packet_loss_pct": 10,      # BAD sample
        "jitter_ms": 8,
        "bitrate_kbps": 1500,
        "frames_decoded": 400,
    })
    # 3 bad samples for new drone 2 is DEGRADED
    assert m.get_status('drone-2') == 'DEGRADED'

    # drone 1 is FAILED, drone 2 is DEGRADED. Finds both.
    assert m.get_streams_needing_attention() == ['drone-1', 'drone-2']

    m.process_sample({
        "sample_id": "sample-11",
        "stream_id": "drone-1",
        "timestamp": 130,
        "rtt_ms": 85,
        "packet_loss_pct": 1.2,
        "jitter_ms": 8,
        "bitrate_kbps": 1500,
        "frames_decoded": 600,
    })
    # 2 good samples (for drone #1) after 'FAILED' changes status to 'HEALTHY'
    assert m.get_status('drone-1') == 'HEALTHY'
    print("All tests passed!")
