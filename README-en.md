[한국어](README.md) | [English](README-en.md)

# AnyControl v1.0.0

#### An entry in the 2026 Korea University × AWS AI INNOVATORS CHALLENGE

**Team:** 아무거나 (Amugeona) · **Team member:** 김삼 (Kim Sam)

*All you need is one camera. A cup on your desk, an ordinary pen, or even your bare hands can become a mouse, a keyboard, or a gamepad. AnyControl recognizes multiple objects at once, remembers them when they are occluded, and finds them again. All processing runs in real time, on-device, so it works without an internet connection.*

A local web app for macOS that tracks objects and hands through a camera and turns their movement into mouse and keyboard input. It includes object mappings, hand mouse control, pen and finger drawing, and practice demos.

## Download and install

1. Download `AnyControl-v1.0.0-macOS.command` from [GitHub Releases](https://github.com/maboloar/anycontrol/releases). Also keep `AnyControl-Uninstall-v1.0.0-macOS.command` for removal. **The Source code archives are not installers for regular users.**
2. Double-click the launcher `.command` file. Terminal opens and installation begins. The first installation may take several minutes, depending on your internet connection.
3. Allow camera access when prompted. AnyControl opens automatically in your browser when setup finishes.
4. Follow the tutorial to select a camera and configure object or hand input. To control your Mac's actual mouse and keyboard, grant Accessibility permission and enable actual input in the app.

**Automatic dependency installation:** Running the `.command` executable automatically installs the required Python and all libraries (requirements). Nothing needs to be installed beforehand.

The default installation location is `~/Library/Application Support/AnyControl/`. Python, libraries, the app and logs are stored there. Saved mappings are kept in `profiles/`. The executable includes tracking models and the built web interface.

If macOS security blocks the downloaded file, see **Troubleshooting** at the bottom.

## Requirements

### Required to run

- **OS and hardware:** macOS 14 or later, Apple Silicon (M1 or later)
- **Memory:** 8GB minimum; 16GB recommended
- **First installation:** At least 4GB of free disk space and internet access
- **Camera:** Required — an iPhone connected over USB with Continuity Camera is recommended
- **Permissions:** Camera access required; Accessibility permission required for actual OS input
- **Installation:** Python and libraries are installed automatically by the `.command` file; no prerequisites to install
- **Offline use:** Available after the first installation

### Additional development requirements

- **Python:** 3.12 or later; 3.13 recommended
- **Node.js:** 22.12 or later for builds / 22.22.2 or later, or 24.15 or later, for tests
- **Dependencies:** Install according to [requirements-macos-arm64.lock](packaging/requirements-macos-arm64.lock)

See the [development guide](DEVELOPMENT.md) for running from source, testing and building releases. Regular users do not need Node.js, Homebrew or Xcode.

## Connect an iPhone — Continuity Camera (연속성 카메라)

This Apple feature lets you use an iPhone as your Mac's webcam. **A wired USB connection is recommended.** The following conditions come from [Apple's official Continuity Camera guide](https://support.apple.com/en-us/102546).

- iPhone XR or later, running iOS 16 or later. AnyControl requires macOS 14 or later on the Mac.
- Both devices must be signed in to **the same Apple Account with two-factor authentication**.
- Enable **Continuity Camera** under **Settings → General → AirPlay & Continuity** (or **AirPlay & Handoff**) on the iPhone.
- Keep the devices near each other with Wi-Fi and Bluetooth enabled. Turn off the iPhone's Personal Hotspot and the Mac's internet sharing.
- For USB, set the iPhone to **trust this computer**. For wireless use, do not use AirPlay or Sidecar on the Mac.

Connect the iPhone over USB, lock it and secure it on a stand with its rear camera facing the objects or hands to track. In AnyControl, use **Camera → Refresh devices** (카메라 → 장치 새로고침), then select the iPhone. A connected camera may also be selected automatically. Desk View is available on supported iPhones; see Apple's guide for device requirements.

## Use and quit

- **Object input:** Select an object in the camera view, then configure its input mappings.
- **Hand and pen input:** Choose a mode in the mouse or drawing panel and follow the calibration prompts.
- **Profiles:** Save frequently used mappings and load them on your next run.
- **Emergency stop:** Press `Esc` to stop input output and release held keys and buttons.

**To quit, close the AnyControl browser tab.** If several tabs are open, close all of them. After about five seconds, the server and the program running in Terminal exit automatically. If the Terminal window remains open, you can close it (automatic window closing depends on Terminal settings).

To run again, double-click the same launcher `.command` file. To update, quit the existing app and open the launcher from the new release. Saved profiles are retained.

## Uninstall

Double-click `AnyControl-Uninstall-v1.0.0-macOS.command` and follow the Terminal prompts. If AnyControl is running, you are asked whether to stop it. You are also asked separately whether to delete saved profiles (kept by default).

The installed app, Python, libraries, cache and logs are removed. Downloaded `.command` files and macOS permission entries remain; remove them manually if needed.

## Third-party components

Object tracking uses EfficientTAM. The optional hand engine uses MediaPipe, and the default hand engine uses Apple Vision. See [third-party components](THIRD_PARTY.md) for sources and licenses of external code and bundled components.

## Troubleshooting

| Problem | Solution |
|---|---|
| macOS security blocks the `.command` file | Verify that it came from the official release, then allow it under **System Settings → Privacy & Security → Open Anyway**. The current distribution is not signed or notarized. |
| Permission denied when launching | Type `chmod +x ` in Terminal, drag the executable into the window and press Enter. Then double-click it again. |
| Installation fails or stops | Check internet access and at least 4GB of free space, then run the same file again. Logs are in `~/Library/Application Support/AnyControl/logs/`. |
| The browser does not open automatically | Open the address printed in Terminal. The default is `http://127.0.0.1:8767`; another port is chosen if it is occupied. |
| Camera missing or black image | Check macOS camera permission, close other apps using the camera, and refresh devices. For iPhone, check the Continuity Camera conditions above and USB trust settings. |
| Actual mouse or keyboard input does not work | Under **System Settings → Privacy & Security → Accessibility**, grant permission to the executable identified by the app and enable actual input. Restart AnyControl if needed. |
| Tracking jitters or loses the object | Improve lighting and keep the camera and object steady. Use an object that stands out from the background, then reselect or recalibrate. Similar objects and objects heavily covered by a hand may be difficult to track. |
| Closing the tab does not quit the app | Check for other AnyControl tabs and wait briefly. If it keeps running, press `Ctrl+C` in its Terminal window. |

If the libraries need repair, run this command from the directory containing the executable:

```bash
./AnyControl-v1.0.0-macOS.command --repair
```

If the issue persists, report your macOS version, Mac model and error message in [GitHub Issues](https://github.com/maboloar/anycontrol/issues). Check logs for personal information, such as your username or private paths, before attaching them.
