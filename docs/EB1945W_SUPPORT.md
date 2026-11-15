# EB / PowerLite 1945W support audit

## Evidence and scope

The local projector identifies itself through PJLink as `EB/PL-1945W/C745WN`.
An authorized TCP registration query returned a 1280×800 frame size, native
JPEG encodings, and the legacy EasyMP capability record. The committed reply
fixture has its IP, MAC, and name replaced; it contains no screen contents.

Native video framing is adapted from these MIT-licensed primary sources:

- [epson-projector-linux](https://github.com/maxxcleiton/epson-projector-linux):
  legacy `0x0004/0x0005` connection, `0xC8` display configuration, and
  `0x0006/0x0007` disconnect.
- [LibreMP](https://github.com/MuazTPM-YT/libre-mp/tree/1a509659a167af031ea24edfafa1c4e98ab4e7a7):
  capability records, JPEG tiles, and compact JPEG length encoding. Its
  newer `0x0101` login timed out on this projector; the legacy login succeeded.
- [Epson 1945W User's Guide](https://files.support.epson.com/pdf/pl1940/pl1940ug.pdf).
- Bundled `docs/ref_files/ESCVP21 command guide for business projector Rev.G.xlsx`,
  sheet 17, EB-1945W columns: command names, ranges, key codes, and sources.
- [Epson networking white paper](https://mediaserver.goepson.com/ImConvServlet/imconv/2317217ed2968c78f528813b95bc1005b722ff2b/original?assetDescr=document&use=productpictures):
  TCP 3620 for session control, TCP 3621 for image/audio transfer, TCP 3629
  for ESC/VP.net control. Port numbers alone do not specify the wire format.

## Implemented projection path

1. Register over TCP 3620 using `EEMP0100`, local IPv4, command 2, and its
   length-delimited payload. Parse complete responses across TCP fragments.
2. Read identity and capability messages (3 and 0x15); bound record sizes,
   require JPEG support, and use the advertised frame dimensions and tile limits.
3. Send the legacy connection command 4 with the reported MAC, negotiated
   frame size, and the user-provided keyword field. Require response 5.
4. Open video and auxiliary TCP 3621 channels. Send the native `EPRD0600`
   display configuration and require the projector's video-ready message 0x16.
5. Capture only after desktop permission. On Wayland, use the file descriptor
   from `OpenPipeWireRemote`; handle the actual RGB row stride. Keep only the
   newest queued frame so a slow projector cannot accumulate captured screens.
6. Encode JPEG tiles with position/size descriptors and compact byte lengths.
   Send changed tiles, refresh the full frame once a second, preserve aspect
   ratio, and service the control channel even when the image is unchanged.
7. Send command 10 keepalives. Surface remote session closure. On Stop or normal
   window close, send command 6 and wait up to three seconds for reply 7.

The GUI reports session acceptance and frame transmission, not proof of visible
projection. Hardware evidence is stronger: the user confirmed that the native
color-bar test appeared, and a separate GStreamer appsink test sent 33 frames.
A mock TCP projector checks registration, fragmented replies, connection,
video configuration, JPEG decoding, heartbeat, and acknowledged disconnect.

## GUI action audit

| GUI feature | Result / implementation |
| --- | --- |
| Discovery / manual IP / aliases / device persistence | Existing paths retained. Native registration and capabilities are validated again before every cast. |
| Screen/window mirror | Native legacy EasyMP TCP JPEG replaces the unacknowledged RTP default. Desktop capture requires user consent. |
| Test patterns | Uses the same native transport and negotiated dimensions. A failed session cannot show a successful streaming state. |
| Stop / Quit / window close | Stops capture and sends native disconnect. Closing the window now quits instead of leaving a hidden client holding projector sockets. |
| Power / device-info wake button | Device-info action now uses actual network power-on rather than an unverified Wake-on-LAN magic packet. Existing `PWR ON/OFF`; hardware power cycling deliberately excluded from validation. |
| Input | Model-specific source list omits nonexistent HDMI2/S-Video inputs; source status synchronization blocks its change handler. |
| Volume / mute / freeze | Read, set to current value, and read back successfully on hardware. Zero volume and false booleans survive status mapping. |
| Brightness / contrast / sharpness | Read/set-current/read passed during native projection. Sharpness uses `SHARP`, not `SHARPNESS`. |
| Horizontal / vertical keystone | Read/set-current/read passed; corrected sliders and validation to the model's 0–255 wire range. |
| Color mode / eco mode | Read/set-current/read passed. Corrected blackboard/whiteboard values and copied status fields through the unified wrapper. |
| Aspect | Corrected normal/wide/auto values to 00/20/30. Query is rejected on LAN; disabled when unavailable. Not hardware-set on HDMI yet. |
| Image adjustments on LAN standby | Reads may succeed while writes fail. Disabled until local projection starts; unsupported/current-input controls stay disabled. |
| Remote buttons | Menu/arrow/volume/user key codes corrected against the model's Epson table. Packet tests; not every physical key was pressed. |
| Sliders | Debounced per setting; status refresh cannot trigger writes; pending updates do not target a newly selected device. |
| Profiles/macros | Enum names such as HDMI1/PRESENTATION/NORMAL are translated to wire values instead of being sent literally. |
| Console / status export | Existing explicit raw-command and local JSON export paths retained. A raw unsupported command can still legitimately return ERR. |
| Quality | Changes native JPEG compression. Resolution follows projector capabilities rather than an unrelated H.264 preset. |
| Native audio | Experimental opt-in GUI toggle / CLI `cast --audio`. Parses record 7, negotiates advertised PCM, initializes the auxiliary channel, and sends bounded `0xC9` PCM buffers. The local desktop playback monitor and mock TCP delivery pass; sound from the physical projector is unverified. Defaults off; no microphone fallback. |
| Virtual extended monitor | GUI Extend mode and CLI `cast --extend`. GNOME/KDE use the portal's virtual source when supported. Hyprland creates a uniquely named temporary headless output, requires that output in the consent picker, and removes it on Stop, Quit, cancellation, or startup failure. |
| Apple / Android phone mirroring | Linux bridge through optional UxPlay (PIN-protected AirPlay) and scrcpy (authorized wireless Android). GUI pairing and process cleanup implemented; phone-to-projector hardware check pending. Native Miracast is not implemented. |
| Multi-presenter quadrants / moderator | Missing EasyMP layout/arbitration; disabled. The old ASCII `MODERATOR` command does not implement that protocol. |
| Whiteboard / pen/touch | No implemented transport for this projector; disabled. Sending WBSHARE/FCN ASCII commands is insufficient. |
| Encryption | Experimental legacy AES session option; fresh seed, native framing, encrypted video metadata/JPEG/PCM, capability checks, and no plaintext fallback. Binary/OpenSSL vectors and local TCP tests pass; physical encrypted projection is unverified. DES/AESEPCTR remain unimplemented. |
| WebRTC signaling | Existing stub is not used. No evidence that this 1945W needs WebRTC; it successfully accepts legacy EasyMP. |
| Network diagnostics / firewall guidance | Added TCP 3620/3621. No local firewall settings were changed. |

## Limits

The user-provided four-digit keyword is validated and encoded, but keyword-
protected hardware has not been tested. Rejected sessions are not retried and
keywords are not guessed. Busy-session arbitration has not been verified.
Other projector models are unverified.

Removed the legacy discovery implementation's unverified 64-byte UDP request
and guessed capability bits. Discovery now validates TCP registration and
reports the real JPEG frame size. Native casting validates those capabilities
again before connecting.

Unchanged tiles are omitted using the existing validated JPEG framing, with a
full refresh every second and whenever quality changes. Mock transport tests
check idle suppression, one-tile changes, refreshes, and failed-send recovery;
this optimization still needs a physical display check. Native audio is now
implemented for advertised PCM but still needs a projector listening test.
Legacy AES is implemented with offline validation; physical encrypted projection,
DES/AESEPCTR, and multi-presenter control remain outstanding.
Their concrete requirements and research locations are recorded in
[remaining protocol work](REMAINING_PROTOCOLS.md).
Temporary output creation/removal passed on the local Hyprland desktop;
GNOME/KDE virtual sources have mock coverage only. A forced process kill can
leave a Hyprland output until it is removed or the desktop session ends.
Tests cannot establish that a physical image appeared;
that is recorded separately above.

## Validation recorded on 2026-11-15

- Full regression suite: 152 passing tests. Two additional CLI axis/range
  regression cases also passed after the full run.
- Ruff and Python compilation passed. The wheel was built and installed into
  the existing isolated `.venv`; installed transport files matched the source.
- Real registration/discovery reports native EasyMP JPEG at 1280×800.
- Native color bars were visually confirmed by the user. GStreamer synthetic
  capture delivered 33 frames through the same TCP JPEG path.
- During native projection, read/set-current/read checks passed for brightness,
  contrast, sharpness, volume, color mode, eco mode, mute, freeze, and horizontal
  and vertical keystone. Original values were retained.
- No power cycle, physical remote-key sequence, or input-source sweep was run.
  Real desktop sharing through the rebuilt GUI is a separate final visual check.

## Offline follow-up validation

- Final full regression suite: **227 passing tests** in 110.93 seconds. Ruff,
  Python compilation, and wheel build passed. The rebuilt wheel was installed;
  all changed installed modules matched the source byte for byte.
- Legacy AES adds independent key/envelope vectors, encrypted metadata/JPEG/PCM
  delivery over local TCP, capability checks, and fail-closed error coverage.
  AES projection on the physical device remains unverified.
- Phone mirroring adds pairing/authorization, private pairing-code handling,
  owned-process cleanup, and PIN redaction checks. The installed PIN-protected
  AirPlay receiver started and stopped successfully; no phone sender was tested.
- Native capability inspection decodes advertised collaboration limits without
  logging into a projection session. The installed `native-info` command routes
  to the CLI; the captured projector response contains no Multi-PC record.
- 169 regression tests passed after changed-tile and virtual-display changes.
- Native audio adds tests for advertised formats, invalid capability lengths,
  bounds/alignment, auxiliary channel initialization, exact PCM bytes over TCP,
  synthetic GStreamer capture through the real transport, queue bounds, and
  startup cleanup. See [native audio notes](EASYMP_AUDIO.md).
- Local PulseAudio/PipeWire capture resolved `@DEFAULT_MONITOR@` to the actual
  playback monitor and produced 441-byte U8/22050 Hz/mono samples. No audio
  was saved or sent to the powered-off projector.
- Virtual output create/remove succeeded on the running Hyprland desktop and
  left the original outputs intact. GNOME/KDE and physical extended projection
  are still unverified.
