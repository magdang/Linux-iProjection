# Native EasyMP audio

Native PCM audio is implemented as an experimental, explicit opt-in. Use the
GUI's Include audio switch or `linux-iprojection cast HOST --audio`. Video-only
remains the default. This implementation has not been heard on the projector.

## Protocol evidence

The sanitized 1945W registration fixture contains capability record 7:
`01 00 01 0c 00 00 00 00 00 00`. The first byte's bit 0 advertises audio
sending. After the two flag bytes, each pair is an encoding and its format;
zero encoding means an unused slot. Encoding 1 describes fixed-format PCM.

Format byte bits 2–4 select 11025, 12000, 16000, 22050, 24000, 32000, 44100,
or 48000 Hz. Bit 1 selects 8/16 bits; bit 0 selects mono/stereo. The fixture
therefore advertises 22050 Hz, unsigned 8-bit, mono. Encoding 2 uses a different
capability scheme and is not implemented. Unknown encodings are skipped.

The legacy login's payload bytes 44–45 hold encoding and format. The auxiliary
TCP 3621 stream starts with `EPRD0600`, local IPv4, four zero bytes, little-endian
payload length 16, then `d0 00 00 00`, reversed local IPv4, channel 1, and seven
zero bytes. Following audio buffers have a five-byte `c9` + little-endian length
header, then PCM bytes. No guessed RTP payload or codec is used.

Evidence was cross-checked against the locally supplied Epson iProjection 4.10
Windows client's `EMP_PJCON.dll`, SHA-256
`4c70d248b9acb73839b5fb857d81c1931c0ed18b978ce96e299192f9cffe4581`:

| Address | Relevant observation |
| --- | --- |
| `0x180205120` | Reads record 7 flags and two-byte encoding entries. |
| `0x180204640`, `0x180205300`, `0x18026eca0` | Decodes rate, sample width, and channel fields. |
| `0x18021c210` | Serializes the legacy connection fields. |
| `0x18024e690` | Serializes channel initialization. |
| `0x18024f050` | Writes `0xC9`, PCM byte length, and data; encryption is a separate path. |
| `0x1802965b0` | Constructs a PCM WAVE format from the projector's advertised settings. |

These are protocol observations; proprietary binaries and decompiler output are
excluded from the repository. The existing MIT-licensed
[LibreMP implementation](https://github.com/MuazTPM-YT/libre-mp) independently
shows the channel initializer and `0xC9` framing, but sends silent buffers.
Its silence alone was insufficient to establish the PCM format.

## Capture and checks

GStreamer's `pulsesrc` uses the explicit `@DEFAULT_MONITOR@` playback source,
followed by audio conversion/resampling to the negotiated PCM format. There is
no microphone fallback. The source works with PulseAudio or pipewire-pulse;
missing plugins or a failed monitor stop startup with an error. Audio has a
bounded five-buffer queue. Starting with audio enabled requires an audio buffer
to be transmitted as well as a video frame; byte transmission does not prove
audible playback.

Tests verify the sanitized capability record, alignment/size limits, login
fields, exact channel bytes, PCM delivery to a local TCP projector, and actual
GStreamer synthetic audio through the native sender. A separate local capture
confirmed the real playback monitor and the negotiated U8/22050/mono format.
The next hardware check is a listening test with audio explicitly enabled;
volume and mute are left under the user's control.

API references: [GStreamer pulsesrc](https://gstreamer.freedesktop.org/documentation/pulseaudio/pulsesrc.html),
[PulseAudio default source names](https://github.com/pulseaudio/pulseaudio/blob/master/src/utils/pacat.c).
