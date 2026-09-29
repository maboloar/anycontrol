# 외부 구성요소 / Third-party components

- **EfficientTAM**: [upstream](https://github.com/yformer/EfficientTAM). Vendored source in `third_party/EfficientTAM/`, runtime checkpoint `models/efficienttam_ti_512x512.pt`. Apache 2.0 license retained in [LICENSE](third_party/EfficientTAM/LICENSE).
- **MediaPipe**: [upstream](https://github.com/google-ai-edge/mediapipe). Runtime hand model `models/hand_landmarker.task`. Apache 2.0 license in [mediapipe-LICENSE](packaging/licenses/mediapipe-LICENSE).
- **Apple Vision**: macOS system framework; no separate bundled model.
- **React, React DOM, Zustand**: frontend libraries; license texts in `packaging/licenses/`.
- **uv 0.12.19**: [upstream](https://github.com/astral-sh/uv). Bundled installer binary; Apache 2.0 and MIT license texts in `packaging/licenses/`.

Python 라이브러리의 버전·해시는 [잠금 파일](packaging/requirements-macos-arm64.lock)에, 프런트엔드 의존성은 [npm 잠금 파일](frontend/package-lock.json)에 있습니다. 설치된 라이브러리의 라이선스는 해당 패키지에 포함됩니다.
Python versions and hashes are in the lock file; frontend dependencies are in the npm lock file. Installed libraries retain their package license information.
