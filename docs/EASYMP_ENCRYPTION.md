# Legacy EasyMP AES

The GUI's Legacy AES switch and CLI `cast HOST --encryption aes` now negotiate
the older AES mode advertised by the 1945W. Test patterns accept the same flag.
The user confirmed an AES image and live counter on the physical 1945W on
2026-11-15. A separate 45-second run sent 82 frame updates and disconnected
cleanly. An earlier run timed out, so long-session reliability remains unproven.
Install the optional `linux-iprojection[encryption]` dependency for AES support.

## Implemented wire path

- Require record 8's AES capability bit before sending a login.
- Generate a fresh nonzero eight-byte seed. Legacy login byte 4 selects mode 2
  (AES); bytes 5–12 carry that seed. Do not alter the user keyword or guess it.
- Derive the legacy eight-byte value with four independent 17-bit shift
  registers, then repeat it for the AES-128 key.
- Prefix each protected payload with its four-byte big-endian plaintext length
  and twelve zero bytes. Pad to a 16-byte boundary with the padding-byte count;
  do not add a block when already aligned. Encrypt the envelope with AES-ECB.
- Keep EPRD headers clear, updating their lengths for encrypted video metadata
  and JPEG data. Protect the complete audio `0xC9` header plus PCM buffer.
  Channel initialization and EEMP session control retain their protocol framing.
- Reject unsupported capability, unavailable crypto, malformed seed, and remote
  refusals. There is no retry using unencrypted video/audio.

This reproduces a legacy compatibility protocol. The seed is sent on the wire
and the scheme has no message authentication; it is not modern secure transport
and should not be relied on to protect sensitive screen content on an untrusted
network. AES support does not implement DES or the separate AESEPCTR scheme.

## Evidence and checks

Addresses in the Epson 4.10 DLL identified in [the audio notes](EASYMP_AUDIO.md):
`0x18021c210` selects the login mode/seed; `0x18023edd0` derives the key;
`0x18023ed60` creates the length envelope; `0x1802a53c0` selects AES-128 ECB;
`0x1802501e0` frames picture metadata; `0x18024f050` frames audio;
`0x18024fcd0` applies padding/encryption; `0x180228410` handles legacy refusals.

Four key-derivation vectors were obtained by running the isolated, relocation-
free vendor derivation routine locally, then compared with the independent
Python implementation. A fixed envelope vector was independently generated
with OpenSSL. Tests decrypt video metadata, JPEG, and PCM sent over real local
TCP sockets, verify exact framing/padding, and ensure failures do not cause a
plaintext login. Vendor executable code is not included in the tests or package.
Encrypted video is hardware-confirmed on this projector; encrypted audio and
other projector models remain unverified.
