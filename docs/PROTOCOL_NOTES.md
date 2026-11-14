# Epson Projector Protocol Notes

Documentation compiled directly from Epson network protocol specifications and public technical documentation. Sufficient detail for reimplementation.

## ESC/VP.net Control Protocol

### Connection
- TCP port 3629
- 16-byte handshake: client sends `ESC/VP.net\x10\x03\x00\x00\x00\x00`
- Successful CONNECT response: `ESC/VP.net\x10\x03\x00\x00\x20\x00` (status `0x20`, no additional headers)
- Commands then use the same TCP connection; no initial `:` prompt is required
- See [Epson ESC/VP.net Software Development Manual](https://www.epson.com.au/d/pub/epson/techtips/escvp.netmanual_e_f.pdf), sections 5.4.1 and 5.6.3

### Command Format
- ASCII text commands terminated by `\r` (carriage return)
- Responses terminated by `\r\n` followed by `:` prompt
- Error responses: `ERR=XX` where XX is error code

### Known Commands
| Command | Description | Response |
|---------|-------------|----------|
| PWR ON | Power on | PWR=01 |
| PWR OFF | Power off | PWR=00 |
| PWR? | Query power state | PWR=XX (00=off,01=on,02=warmup,03=cooldown,04=standby,05=abnormal) |
| SOURCE XX | Set input source | SOURCE=XX |
| SOURCE? | Query input source | SOURCE=XX |
| MUTE ON/OFF | A/V mute | (no response body) |
| LAMP? | Query lamp hours | LAMP=XXXX YY (hours + status) |
| ERR? | Query error state | ERR=XX |
| SNO? | Query serial number | SNO=XXXXXXXXX |
| VOL? | Query volume level | VOL=XX |
| VOL XX | Set volume (0-255) | (no response body) |
| FREEZE ON/OFF | Freeze/unfreeze image | (no response body) |
| BRIGHT XX | Set brightness (1-255) | (no response body) |
| CONTRAST XX | Set contrast (0-255) | (no response body) |
| CMODE XX | Set color mode | (no response body) |
| ASPECT XX | Set aspect ratio | (no response body) |
| LUMINANCE XX | Set eco mode (00=normal, 01=eco) | (no response body) |
| KEY XX | Simulate remote key press | (no response body) |
| HKEYSTONE XX | Horizontal keystone (-60 to 60) | (no response body) |
| VKEYSTONE XX | Vertical keystone (-60 to 60) | (no response body) |
| PNAME? | Query projector name | PNAME=string |
| SIGNAL? | Query signal status | SIGNAL=01 (present) / SIGNAL=00 (absent) |
| FILTER? | Query filter hours | FILTER=XXXX |

### Enterprise Commands (Reverse-engineered from EMP_PJCON.dll)
| Command | Description |
|---------|-------------|
| MODERATOR ON/OFF | Multi-PC moderator mode |
| WBSHARE ON/OFF | Whiteboard sharing |
| FCN ON/OFF | Forward Coordinates (interactive pen/touch) |
| ENCRYPT mode | Stream encryption (OFF, AES, DES, AESEPCTR) |

### Input Source Codes
| Code | Source | Confirmed Models |
|------|--------|-----------------|
| 10 | VGA/Computer 1 | EB-series, EX-series |
| 11 | Computer 1 (alt) | Some PowerLite models |
| 20 | VGA/Computer 2 | EB-series |
| 21 | Computer 2 (alt) | Some PowerLite models |
| 30 | HDMI 1 | All modern models |
| 41 | Video (composite) | EB-series |
| 42 | S-Video | Older EB-series |
| 52 | USB | EB-series, EX-series |
| 53 | LAN/Wireless LAN | EB-series (iProjection) |
| 56 | Wireless HDMI | Newer models |
| A0 | HDMI 2 | Dual-HDMI models |
| F1 | iProjection virtual source 1 | All iProjection models |
| F2 | iProjection virtual source 2 | All iProjection models |

### Firmware Quirks
- Keep-alive required: some firmware drops TCP after ~30s idle. Send `PWR?\r` periodically.
- Some older firmware sends `\r:` instead of `\r\n:` (handle both).

## Discovery

### mDNS/DNS-SD

Service types:
- `_epson._tcp.local.` - Epson network projectors (iProjection/EasyMP)
- `_eshare._tcp.local.` - EShare wireless display receivers
- `_http._tcp.local.` - Generic HTTP devices (filtered by keywords)
- `_pjlink._tcp.local.` - PJLink-compatible projectors

### Native EasyMP registration

The EB/PowerLite 1945W responds on TCP 3620 to a 68-byte registration request
(command 2). Its `EEMP0100` response messages use a 20-byte header: identifier,
sender IPv4, little-endian command, and little-endian payload length. Identity
is in command 3; capabilities are length-delimited records in command 0x15.

Do not infer JPEG, audio, encryption, or WebRTC support from an arbitrary byte
at offset 16. The old UDP packet/flag assumptions have been removed.

## Screen Casting Protocol

The EB/PowerLite 1945W uses native EasyMP TCP projection. The implemented legacy
connection flow is 0x0004/0x0005 on TCP 3620, video-ready 0x0016, JPEG tiles on
TCP 3621, keepalive 0x000A, and disconnect 0x0006/0x0007. The frame dimensions
come from the projector (1280×800 on the available hardware).

`EPRD0600` display metadata uses a little-endian length. JPEG blocks use a
big-endian length, tile count, and tile coordinates. Each tile has encoding 7
and a 0x90 compact JPEG byte-length tag. Raw RTP H.264 or JPEG on UDP 5004 is
not this protocol and has not projected an image on the tested 1945W.

See [the support audit](EB1945W_SUPPORT.md) for packet sources, the exact scope
of hardware verification, GUI fixes, and missing audio/security/collaboration
features. `signaling.py` remains an unused WebRTC stub; it is not evidence that
this older projector needs WebRTC.

### Desktop capture

Use the desktop's ScreenCast permission flow and retain its session handle.
Call `OpenPipeWireRemote` and pass the returned file descriptor to `pipewiresrc`.
The native capture path handles RGB row stride, requests an embedded cursor,
and bounds the frame queue. Refusal cancels the cast without a synthetic-screen
fallback. Screen capture is separate from projector session acceptance.

### Raw RTP compatibility path

The previous RTP/UDP sender is retained only behind explicit CLI
`--transport rtp`. Selecting an encoder or opening a UDP socket does not
establish compatibility with an Epson network-screen receiver.
