# Third-Party Protocols, Specifications & Dependencies

## Epson ESC/VP.net & ESC/VP21

Command protocol logic is implemented directly from Epson's publicly available "ESC/VP.net Software Development Manual" and ESC/VP21 command guides.

## Open Networking Standards

Network discovery and media streaming are implemented using standard open networking protocols: mDNS/DNS-SD for device discovery, RTP over UDP for media streaming, and PipeWire via the XDG Desktop Portal specification for screen capture.

## Bundled GStreamer H.264 Encoder (Flatpak only)

The Flatpak package bundles a `libgstx264.so` GStreamer plugin and its
`libx264` dependency so that `x264enc` is available inside the sandbox. These
are built from source during the Flatpak build and installed under
`/app/lib/gstreamer-1.0`.

| Component | Version / source | License |
| --------- | ---------------- | ------- |
| x264 | commit `b35605ace3ddf7c1a5d67a2eb553f034aef41d55` (`stable` branch, <https://code.videolan.org/videolan/x264>) | GPL-2.0-or-later |
| gst-plugins-ugly (x264enc element) | 1.24.12, <https://gstreamer.freedesktop.org/src/gst-plugins-ugly/> | LGPL-2.1-or-later; the `x264` plugin is distributed under GPL-2.0-or-later because it links against libx264 |

Source archives:
- gst-plugins-ugly 1.24.12: `https://gstreamer.freedesktop.org/src/gst-plugins-ugly/gst-plugins-ugly-1.24.12.tar.xz` (SHA-256 `19ed6eef4ea1a742234fb35e2cdb107168595a4dd409a9fac0b7a16543eee78b`)

This project is licensed AGPL-3.0-or-later. GPL-2.0-or-later code may be
combined with AGPL-3.0-or-later code (the GPLv2 component is distributed under
GPL-3.0-or-later, which is one-way compatible with AGPL-3.0-or-later). The
bundled encoder is only linked at runtime; it is not incorporated into the
application source.

## Python Dependencies

The application depends on PyGObject (GTK4/libadwaita bindings), zeroconf,
pystray, and Pillow. See `pyproject.toml` for the declared versions and their
licenses (all LGPL/MIT/BSD compatible with the project license).

## Native EasyMP interoperability

`easymp.py` adapts legacy EEMP connection and EPRD JPEG framing from
[epson-projector-linux](https://github.com/maxxcleiton/epson-projector-linux),
and capability parsing and JPEG length framing from
[LibreMP](https://github.com/MuazTPM-YT/libre-mp) commit
`1a509659a167af031ea24edfafa1c4e98ab4e7a7`. The 1945W registration fixture was
collected on authorized local hardware, with its name, IP, and MAC replaced.
No captured screen contents or authentication keywords are included.

Both references permit reuse under the MIT license; their notices follow.

```text
MIT License

Copyright (c) 2026 Muaz Ismail Mohammed

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

```text
MIT License

Copyright (c) 2026 Open Source Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
