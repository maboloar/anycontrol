[한국어](README.md) | [English](README-en.md)

# AnyControl v1.8.0

#### Entry for the 2026 Korea University × AWS AI INNOVATORS CHALLENGE

*One camera is enough. A cup on your desk, an ordinary pen or your bare hand becomes a mouse, a keyboard or a gamepad. It recognizes several objects at once and finds them again after they are hidden. Everything runs in real time, on device, with no internet connection.*

AnyControl is a local macOS web app that tracks objects and hands with a camera and turns their movement into mouse and keyboard input. It offers object mappings, a bare-hand mouse, pen and index-finger drawing, and practice demos.

## Download and install

> This source tree is v1.8.0. The v1.8.0 launcher is built in `releases/`; uploading it to GitHub Releases is a separate step. Check the published release when downloading.

1. Download `AnyControl-v1.8.0-macOS.command` from [GitHub Releases](https://github.com/maboloar/anycontrol/releases). Also keep `AnyControl-Uninstall-v1.8.0-macOS.command` for removal. **The Source code archives are not installers for regular users.**
2. Double-click the launcher `.command`. **If macOS blocks it or says you don't have permission to open it, first follow [first-launch security and permissions](#first-launch-permissions).** A Terminal window opens and installation runs. The first install can take a few minutes depending on your connection.
3. Allow camera access. When installation finishes, AnyControl opens in your browser.
4. Follow the on-screen tutorial to choose a camera and set up object or hand input. To control the real Mac mouse and keyboard, grant Accessibility permission and turn on real input in the app.

**Dependencies install automatically:** running the `.command` installs Python and every required library. Nothing has to be installed beforehand.

The default install location is `~/Library/Application Support/AnyControl/`. Python, libraries, the program and logs go there; saved mappings are kept in `profiles/`. The launcher bundles the tracking models and the web UI.

On first launch a **security block** and then an **execute-permission error** may appear. Fix them in order using the [first-launch guide](#first-launch-permissions) in Troubleshooting.

## Requirements

### To run

- **OS / device:** macOS 14 or later, Apple Silicon (M1 or later)
- **Memory:** 8 GB or more, 16 GB recommended
- **First install:** 4 GB of free disk space and an internet connection
- **Camera:** required — an iPhone via Continuity Camera over USB is recommended
- **Permissions:** camera required; Accessibility for real OS input
- **Install:** the `.command` installs Python and libraries automatically; no prerequisites
- **Offline use:** works without internet after the first install

### For development

- **Python:** 3.12 or later, 3.13 recommended
- **Node.js:** 22.12+ to build / 22.22.2+ or 24.15+ to run tests
- **Dependencies:** install from [requirements-macos-arm64.lock](packaging/requirements-macos-arm64.lock)

See the [development guide](DEVELOPMENT.md) for running from source, tests and building the launcher. Regular users do not need Node.js, Homebrew or Xcode.

## iPhone as a webcam — Continuity Camera

Continuity Camera is Apple's feature for using an iPhone as a Mac webcam. **A wired USB connection is recommended.** Requirements follow Apple's [Continuity Camera guide](https://support.apple.com/en-us/102546).

- iPhone XR or later with iOS 16 or later. AnyControl itself needs macOS 14 or later.
- Both devices signed in to the **same Apple Account with two-factor authentication**.
- On the iPhone, turn on **Continuity Camera** in **Settings → General → AirPlay & Continuity** (or **AirPlay & Handoff**).
- Keep the devices close with Wi‑Fi and Bluetooth on. Turn off iPhone Personal Hotspot and Mac Internet Sharing.
- Over USB, **trust this computer** on the iPhone. Wirelessly, don't use AirPlay or Sidecar on the Mac.

Connect the iPhone by USB, lock it and mount it so the rear camera faces the objects and hands to track. In AnyControl press **Camera → Refresh devices** and choose the iPhone; a connected camera may also be selected automatically. Desk View works on supported iPhones; see Apple's guide for device conditions.

## Use and quit

- **Object mouse:** drag around an object in the camera view to register it, then pick it in the Mouse panel. By default sideways movement moves the cursor left/right and moving toward/away from the camera moves it up/down, using the object's size change as the depth signal. The depth model can be chosen in advanced settings. **The object mouse only moves the cursor and does not use hand tracking** (hand clicks and the one-hand hybrid were removed). A pen object clicks when it touches the desk (Beta).
- **Bare-hand mouse:** moves by the hand's XY position in the video. Thumb + index pinch = left press/drag, thumb + middle = right press. Scroll by raising only the index and middle fingers (thumb, ring and little finger folded) and moving up or down.
- **Quick auto calibration:** run it after registering/selecting the target. It asks for a short rest, a left-right sweep from wherever you are, then a near-far or up-down sweep — no need to return to the centre each time. The bare-hand mouse can optionally calibrate clicks and scrolling (the object mouse calibrates movement only); the pen has its own touch/lift steps. Review the result before applying; cancelling keeps the old settings.
- **Bare-hand card and patch jacks:** the hand-mapping switch on the Objects panel applies only to bare-hand jacks; object touch, the bare-hand mouse and drawing follow their own settings. Hand jacks can also use palm X/Y as continuous inputs; buttons use the thumb+index or thumb+middle pinch. Change input gesture, sensitivity and direction from the cable.
- **Object touch:** requires two consecutive frames of visual evidence that a recognized hand actually covers part of the object's original mask. Background changed by a hand behind the object, gaps between fingers, holes in the object, and shadows or lighting changes that keep the surface texture are not counted. Fingertips, the palm and the side of a finger work; default sensitivity is 70%. At first, lift your hand off the object briefly so it can capture the reference look. Input releases when the object mask is missing or the hand/object disappears, independent of the hand-mapping switch. Covering the object in mid-air versus touching it, hands or gloves the same colour as the object, and shadows cannot be fully separated from a single video, so ambiguous evidence does not press. If hand detection drops out briefly (under 0.6 s) while the finger stays, the touch is kept. When the gauge under an object fills but no touch registers, the camera view shows the reason in yellow (hand not recognized, lighting changed, object pattern still visible, …). Turn on diagnostics with **Show touch detection** in advanced mode.
- **Mappings and profiles:** **Add mapping** at the top and bottom and the cable editor use the same editor. Choose input type, object/hand, axis/gesture and output, then press Add; the jack, row and cable appear together. Hands offer palm X/Y and the thumb+index/middle pinches in both places, and sensitivity and details (range, invert, deadzone, curve, press/release, smoothing, on-lost) stay in sync. Custom jacks with descriptions survive Reset all and reconnect with the chosen gesture and transform. Connect by dragging a jack or clicking both ends; left-click a cable to edit input, sensitivity and direction, or remove it with **Unmap** or a middle click on the cable. Renaming an object keeps its connections. **Reset all mappings** runs on a second press and removes everything, including connections the Mapping panel hides such as DJ ones; objects and saved profiles are kept.
- **Tracking protection:** spike suppression is on by default. When objects overlap, AnyControl shows **Overlap** and briefly pauses appearance learning and re-segmentation so they don't learn each other. Full occlusion and look-alike objects can still be hard.
- **Practice demos:** racing, Pong, air hockey, fruit catch, zombie survival, DJ set, virtual desktop and pen/hand drawing. Demos appear in one full-width row below all panels, every game starts in 1P, and `Space` pauses games. The virtual desktop needs the bare-hand or object mouse turned on (otherwise it shows a hint and a **Go to Mouse panel** button). DJ connections are handled only in the DJ panel's patch bay; while the DJ set is open the Mapping panel hides game jacks and DJ connections. The DJ patch bay sits above the deck and uses a 124 BPM melodic-house loop and clap sounds. The pen feature is **Beta**.
- **Display and performance:** basic mode includes input mirroring and the performance panel. Video mirroring changes only the display; full input mirroring changes control direction. Drag a panel by its title bar and restore with **Reset layout**.
- **Guide and idle screen:** **Guide**, right of the title, opens the follow-along tutorial (register an object → connect a function → pick a game → auto-map → play). Each step turns green and advances when you complete it, and you can **Skip**. In advanced mode `Advanced mode · backend v1.8.0` appears in small type under the title. After 20 seconds without keyboard or mouse input, a large purple hint appears next to Guide and the whole title bar glows purple. The bar is sticky only while the hint shows; after input it waits 10 seconds so the hint can be read, then releases. Returning from the demo screen shows the hint immediately. Closing it with the × on its right keeps it hidden until the next demo screen (or a page reload). While real OS input is active, the stop-warning colours take priority.
- **Game controls:** every game's **Start/Resume** and **Restart** are the big buttons right of the auto-map box. **Sensitivity** next to auto-map adjusts the current game's left-right and depth/up-down axes together (both controllers in 2P). It changes the same ranges as the Mapping panel, so both stay in sync and per-axis ratios and inversion are kept; differing axes show **Per-axis** with the average factor. Single-player air hockey offers **AI difficulty: Easy · Normal · Hard**; the default Normal is a little easier than before.
- **Reset all settings:** press the dark red button twice. Registered objects, current mappings and input/tracking/calibration/display settings are reset and real output is turned off. Saved profiles, custom jacks and the current camera connection/resolution/FPS are kept. The idle demo screen appears after 120 seconds by default and performs the same reset, including layout and panel sizes.
- **Emergency stop:** `Esc` stops input output and releases held keys and buttons. Real Mac control needs Accessibility permission and output enabled.

**Long sessions:** for booth use of six or more hours a day, a hand-detection memory leak and a memory spike caused by diverging tracking scale were fixed (memory flattened at about 1.5 GB in a 10-minute recorded-video run).

**To quit, close the AnyControl browser tab.** Close all tabs if you opened several. About 5 seconds later the server and the program running in Terminal exit. If the Terminal window itself stays open you can close it (auto-close depends on Terminal settings).

To use it again, double-click the same launcher. To update, quit the app and open the new release's launcher; saved profiles are kept.

### Game auto-mapping

1. Register the objects to use in the video and choose 1P or 2P (zombies are 1P only).
2. Above the game, pick the controller and control style, then press **Auto-map**. Racing uses sideways movement/tilt; Pong, fruit, zombies and hockey use size/near-far on the desk for up/down, or lifting the object and moving it up/down in the video. Bare hands use video XY.
3. Auto-map creates real virtual-gamepad axis jacks and cables in the Mapping panel. Game examples replace pad-axis connections so axes/triggers from a previous game don't pile up, and keep key, mouse, button and DJ connections. 2P needs two different controllers.
4. Starting without connections shows an auto-map hint. You can also wire game jacks manually in the Mapping panel; choose a game under **Show game jacks** to see them.
5. During play you can change object/hand, input axis, sensitivity, direction and enabled state in the Mapping panel. Changes go through the usual autosave (sent after about 0.3 s). The game and the virtual gamepad view read the same stick/trigger values, never object coordinates or the mouse cursor. Editing inside the app does not pause the game; leaving the window or pressing Esc does.

**Air hockey:** 1P on the left and the computer/2P on the right hit the puck with round mallets into the opponent's goal. Keep the object on the desk and move it sideways and near/far; each player stays in their own half. Faster pushes hit harder; first to 7 goals wins. 1P WASD and 2P arrow keys also work as secondary controls once connected.

All games scale the canvas's real pixel count to the view width and display scale, so resizing and Retina screens keep logical coordinates and collisions identical while lines and text stay sharp. It is capped at about 4 million pixels for performance. The DJ set keeps its own patch bay and on-screen controls.

## Uninstall

Double-click `AnyControl-Uninstall-v1.8.0-macOS.command` and follow the Terminal prompts. It asks before quitting a running AnyControl and separately asks whether to delete saved profiles (kept by default).

The installed program, Python, libraries, caches and logs are removed. The downloaded `.command` files and the macOS permission entries remain; remove them yourself if you like.

## Third-party components

Object tracking uses EfficientTAM; the optional hand engine is MediaPipe and the default hand engine is Apple Vision. Sources and licenses are listed in [third-party components](THIRD_PARTY.md).

## Troubleshooting

| Problem | Fix |
|---|---|
| The `.command` is blocked by security settings | Follow [1. Allow it in macOS security](#security-blocked). |
| "You do not have permission to open the application" | Follow [2. Make the file executable](#execution-permission), then double-click again. |
| Install fails or stalls | Check your connection and 4 GB of free space, then run the same file again. Logs are in `~/Library/Application Support/AnyControl/logs/`. |
| The browser doesn't open | Open the address shown in Terminal. The default is `http://127.0.0.1:8767`; another port is chosen if it's busy. |
| No camera or a black picture | Check macOS camera permission, quit other apps using the camera and refresh devices. For an iPhone, check the Continuity Camera conditions and USB trust above. |
| Real mouse/keyboard input doesn't work | In **System Settings → Privacy & Security → Accessibility**, allow the program the app points to and turn on real input. Restart AnyControl if needed. |
| Tracking jitters or loses the object | Brighten the lighting and keep the camera and object steady. Use an object that stands out from the background, then reselect or calibrate. Look-alike objects or objects largely hidden by a hand can be hard to track. |
| Closing the tab doesn't quit | Check for other AnyControl tabs and wait a moment. If it keeps running, press `Ctrl+C` in its Terminal. |

<a id="first-launch-permissions"></a>

### First launch: security block and execute permission

The first time you open a downloaded `.command`, these two errors **may appear one after the other**. Even after allowing it in security settings, installation won't start if the file lacks execute permission. **Follow the step that matches the error you see.** The launcher and the uninstaller may each need it.

<a id="security-blocked"></a>

#### 1. Blocked by macOS security settings

**Symptom:** macOS says it can't verify the developer or check the file for malware, and blocks it. AnyControl releases are currently not signed or notarized, so this can happen.

1. Make sure you downloaded the file from the [official GitHub Releases](https://github.com/maboloar/anycontrol/releases).
2. Double-click the `.command` in Finder, read the warning and close it.
3. Open **Apple menu () → System Settings → Privacy & Security**.
4. Scroll to **Security** and click **Open Anyway** next to the message about the file.
5. Choose **Open** in the confirmation and authenticate with your login password or Touch ID if asked.

If **Open Anyway** is missing, open the file again and check the settings right after the warning appears. Macs managed by a school or company may not allow it. See [Apple's guide to opening apps](https://support.apple.com/en-us/102445).

If you then see **"you do not have permission…"**, continue with step 2.

<a id="execution-permission"></a>

#### 2. "You do not have permission to open the application"

**Symptom:** macOS says you lack permission to run the file. The download lost its execute bit; add it with `chmod`.

1. Press `⌘ + Space`, search for **Terminal** and open it.
2. Type **`chmod u+x` followed by one space**. Don't press Enter yet.
3. **Drag the downloaded `.command` from Finder into the Terminal window**; its path is filled in.
4. Press Enter. A new prompt with no error means it worked.
5. Go back to Finder and double-click the same `.command` again.

If the file is in **Downloads** you can use this command as is. Otherwise use the drag-and-drop method above.

```bash
chmod u+x "$HOME/Downloads/AnyControl-v1.8.0-macOS.command"
```

If the uninstaller shows the same error, apply it to that file too.

```bash
chmod u+x "$HOME/Downloads/AnyControl-Uninstall-v1.8.0-macOS.command"
```

This **adds execute permission for the current user to that file only**; it doesn't install or run anything. If a security block appears when you reopen it, also complete [step 1](#security-blocked). Apple's explanation: [Make a file executable](https://support.apple.com/guide/terminal/apdd100908f-06b3-4e63-8a87-32e71241bab4/mac).

To repair libraries, run this in the launcher's folder:

```bash
./AnyControl-v1.8.0-macOS.command --repair
```

If that doesn't help, open a [GitHub Issue](https://github.com/maboloar/anycontrol/issues) with your macOS version, Mac model and the error. Check logs for personal information such as user names or paths before attaching them.

### DJ example mappings and deleting objects

**Object example · Auto-map** above the DJ set wires real cables based on how many regular objects you have. With one object: sideways mixes, near/far sets volume, tilt filters, lifting claps, and playback uses the on-screen play buttons (no touch mapping). With two, decks A/B are assigned left to right in the video: touching each object plays/stops its deck and near/far sets its volume; A's sideways/tilt/lift control mix/tempo/clap and B's tilt/lift control filter/echo. With three or more, the first two are used. Only DJ connections are replaced; other mappings stay.

Deleting a registered object immediately removes its current cables; saved profiles are kept. At startup the camera prefers homese → 17sa → FaceTime HD Camera, and you can pick another device from the list. Choosing a different segmentation candidate keeps the same object ID, so its mappings stay connected. The **i** next to advanced performance metrics explains what each measures.

### Gamepad channels and advanced performance

| Game | 1P | 2P |
|---|---|---|
| Racing | Left stick X, RT throttle · LT brake (1P) | Right stick X |
| Pong | Left stick Y | Right stick Y |
| Fruit catch · air hockey | Left stick X/Y | Right stick X/Y |
| Zombie survival | Left stick X/Y | — |

The generic stick/trigger jacks in the Mapping panel drive the same channels. Older game-specific output profiles are converted to pad axes on load; if several old connections target the same axis, the later one wins. Saved files are not overwritten. Example names are **(desk)** / **(video XY)**; the latter controls Y by moving the object up/down in the video. Virtual-pad values are computed even in **View only**; real OS mouse/keyboard output follows the output setting.

Advanced performance adds **capture slot replacements, dropped camera frames, skipped preview decodes, preview size (p50), processed-frame total and object tracking state** to the existing metrics. Each **i** explains its scope. Values the source doesn't provide show as –.

### Connect mappings by clicking the video

1. Register an object first.
2. Pick up a cable from a **function jack** in the Mapping panel, or click an **existing cable**.
3. Click the registered object in the camera video to connect it to that object's card jack. With an existing cable selected, that function's object is replaced. The cable end stays on the **Objects panel**.

Clicking the object in the video first and then a jack does not connect: video clicks cannot start a cable. Connect bare hands through the **bare-hand card jack**, not the hand drawing in the video. Background, unregistered and lost objects are not targets, and clicking the background while holding a cable does not register a new object. ESC cancels. Mirrored and floating previews are supported, with the small preview's letterbox excluded.

### Real OS input in the title bar

Turn on **Output → Real (OS input)**. The title bar itself plays a three-second countdown animation, then turns red while active. Instructions and **Stop (ESC)** sit in the middle of the bar, which stays pinned while counting down or active. No separate banner is added. The stop button and ESC use the emergency-stop path to release real input and held outputs. If a stop request fails because of an input error, the active warning stays visible.
