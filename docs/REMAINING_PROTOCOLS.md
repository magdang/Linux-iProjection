# Remaining 1945W protocol work

This records specific missing pieces, not working features. Existing control,
native JPEG, and experimental PCM implementation/validation are covered in
[the support audit](EB1945W_SUPPORT.md). No queries were sent to the projector
during this offline investigation.

## What the captured projector advertised

The sanitized registration fixture has capability records 1, 2, 3, 4, 5, 7,
8, and 9. Record 1 reports version 10, record 3 reports 1280×800, record 5
includes JPEG, and record 7 includes mono U8 PCM at 22050 Hz. Record 8 is
`9f 03 00 01 00 00 00 00`.

Epson's capability logger identifies record 8 byte 1 bits 0/1/2 as DES, AES,
and AESEPCTR respectively. This reply advertises DES and AES, not AESEPCTR.
Byte 2 bit 3 is whiteboard sharing and is clear. Multi-PC capability record
10 and forward-coordinate record 12 are absent from this reply. Their absence
does not establish that every Epson application or session mode on this model
lacks those features; a different registration/session flow may be needed.

The implementation now decodes record 10's support, moderator, delivery,
thumbnail, coordinate, PIN, version, user/display, and audio limits when present.
Discovery retains this metadata. `linux-iprojection native-info HOST` performs
registration only and prints the advertised features as JSON without logging in
or projecting. An absent record is reported as `null`, rather than inventing
Multi-PC support. Fresh capability replies clear stale feature flags, including
encryption capabilities.

## Missing implementations and concrete research locations

Addresses below refer to the same Epson iProjection 4.10 `EMP_PJCON.dll` hash
recorded in [the audio notes](EASYMP_AUDIO.md). They identify code locations,
not a complete specification or a guarantee that this projector accepts the
newer session flow. Proprietary binaries and decompiler output are not committed.

| Feature | Required work | Relevant locations |
| --- | --- | --- |
| Encrypted legacy projection | AES mode, key derivation, protected video/audio framing, and padding are implemented as an explicit experimental option. Physical AES video/live counter was confirmed on 2026-11-15; encrypted audio, long-session reliability, and DES/AESEPCTR remain outstanding. See [AES notes](EASYMP_ENCRYPTION.md). | `0x180202d00` capability flags; `0x180286950` encoder selection; `0x1802a53c0` AES-128 ECB primitive setup; `0x18024f050` audio framing/padding; `0x1802501e0` picture framing. |
| Multi-PC quadrants | Establish the correct supported collaboration session first; parse user IDs/list, allocate layouts, send active/mirror lists, and handle accepted/rejected updates and timeouts. A client-side crop is insufficient. | `0x180200c70` Multi-PC capability flags/limits; `0x18027d550` active-list state machine; `0x18027d420` mirror-list update; `0x180234990` incoming replies. |
| Moderator controls | Negotiate moderator capability, request/release authority, handle acceptance/refusal, and update UI ownership from replies. | `0x180277720` moderator request; `0x180234990` reply dispatcher, including `0x113` acceptance and `0x114` refusal. |
| Whiteboard | Establish whether the specific model/session advertises the feature, then implement its native session/data channel. The captured feature flag is clear. | Record 8 logger at `0x180202d00`; `MODERATOR`/`WBSHARE` ASCII is not this protocol. |
| Pen/touch | Confirm suitable hardware/capability and implement coordinate-session setup, device identity/calibration, event framing, and teardown. No interactive hardware was established for this 1945W. | Record 12 construction in `0x1801f9310`; `0x18022a2b0` forward-pen session start. |
| Newer collaboration receiver flow | Implement only with evidence the model supports it; includes separate client/server roles and asynchronous state updates beyond the working legacy login. | `0x18023cf60` collaboration server lifecycle; `0x180234990` message dispatch. The tested `0x101` login timed out on this projector. |

The newer dispatcher also handles active-list replies `0x109/0x10a`, mirror-list
replies `0x10c/0x10d`, and user-list message `0x10e`. These identifiers alone do
not specify payloads, session prerequisites, or retry/arbitration behavior.
Sending them without that state machine would create another nonworking button.

AESEPCTR has a distinct implementation involving RSA key generation and AES;
its constructor is at `0x1802a4f00`. It should not be substituted for the older
AES mode advertised by this projector. An ASCII encryption-setting command does
not encrypt any native screen/audio payload.

## Hardware checks still needed

When the projector is available, check real desktop visibility, changed-tile
updates, temporary extended-display output, and opt-in audio playback. Then
collect accepted/refused encrypted and collaboration sessions using an explicitly
supported official client if one becomes available. The current Linux-only
environment provides static protocol evidence and mock tests, not those missing
working-session transcripts. Keep the unsupported GUI controls disabled until
their actual transport and capability checks exist.
