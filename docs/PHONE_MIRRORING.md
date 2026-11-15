# Apple and Android mirroring through Linux

The app can receive phone screens on the Linux computer and forward the chosen
window/screen through native EasyMP. The computer must stay on and connected.
This does not install an AirPlay or Miracast server in the Epson firmware.

## Apple AirPlay

1. In Phone Mirroring, start Apple AirPlay. The app displays receiver name
   **iProjection** and a session PIN.
2. Choose iProjection in Screen Mirroring on the iPhone, iPad, or Mac and enter
   that PIN. UxPlay opens the mirrored display on Linux.
3. Start Casting and select that window. If the desktop picker only offers an
   entire monitor, maximize the phone window and share that monitor; other
   content on the monitor will also be visible.

The optional [UxPlay](https://github.com/FDH2/UxPlay) executable provides the
AirPlay receiver. The app starts it explicitly with PIN authentication, ignores
unrelated UxPlay config, and stops only the process it owns. Closing the app
stops its receivers. No receiver is advertised merely by opening iProjection.
DRM-protected Apple video is outside UxPlay's supported mirroring scope.

## Android alternative to Miracast

The implemented Android route uses [scrcpy](https://github.com/Genymobile/scrcpy)
over an authorized wireless ADB connection on the existing LAN. It is an
alternative to Miracast, not an implementation of the Miracast protocol.

1. On Android 11+, enable Developer options → Wireless debugging.
2. Open Pair device with pairing code. In the app, choose Pair Android and
   enter that screen's IP:port and six-digit code. Enter the separate connection
   IP:port from the main Wireless debugging page in the third field.
3. Start Android Wireless Mirror. Exactly one authorized wireless device must
   be connected. The app ignores unauthorized and USB devices.
4. Start Casting and select **iProjection Android**, or its monitor if window
   selection is unavailable.

Phone input control and clipboard synchronization are disabled. Pairing codes
are supplied to ADB through stdin rather than command-line arguments, and are
not saved by this app. Android/ADB maintains its normal pairing trust; revoke
the pairing or disable Wireless debugging on the phone when it is no longer
needed. The app never enables legacy unauthenticated TCP debugging.

For phone playback audio, enable Include audio before starting the phone mirror
and native cast. Android audio forwarding requires Android 11+ and may be
restricted by an app. Native projector audio remains experimental.

## Why this route instead of claiming Miracast support

[MiracleCast](https://github.com/albfan/miraclecast) implements a Linux Miracast
sink, but its documented setup takes control of Wi-Fi Direct and stops normal
network-management services. That can interrupt the same LAN connection needed
to reach this projector. The local adapter advertises P2P client/GO modes, which
is a capability check, not proof that a full Miracast receiver will work.
The app does not change NetworkManager, wpa_supplicant, radio modes, or firewall
rules. Native Miracast receiving remains unimplemented.

## Dependencies and verification

Install `uxplay` for Apple receiving and `scrcpy` plus `adb` for Android. The app
finds standard PATH executables or executables in its Python environment's bin
directory. A matching local scrcpy server is used when present in that
environment's share/scrcpy directory. Third-party executable code is not bundled
into the Python wheel.

For this local build, UxPlay 1.74 was compiled into the isolated environment;
scrcpy 5.0.1 and its matching server were extracted from Arch's package into the
same environment. Both executables accepted the exact launch options. The
installed PIN-protected AirPlay receiver also started and stopped successfully.
Unit tests cover pairing/authorization, child-process ownership, failure cleanup,
and PIN redaction. No physical Apple/Android sender or projected phone image has
been tested, and no receiver was left running by the build checks.

Primary setup references: [scrcpy wireless connections](https://github.com/Genymobile/scrcpy/blob/master/doc/connection.md#tcpip-wireless),
[scrcpy audio](https://github.com/Genymobile/scrcpy/blob/master/doc/audio.md),
and [UxPlay usage](https://github.com/FDH2/UxPlay#usage).
