# Blender iOS farm trust review

**Baseline** `5e5942b486bb8505cfdfd3c174068d5e023dd369`, Blender 5.3.0. This is an offline review of the checked-in build recipes, workflow and iOS code. No remote artifact, CI run or device traffic was observed.

## Findings

- On a cold preview build, **28 of 64** selected CMake archives have repository-pinned SHA-256 digests. **35 use MD5** and SQLite uses **SHA-1**. The preview uses Blender's HTTPS mirror. Local configuration defaults to upstream sources, including 14 plaintext HTTP URLs. Several pair HTTP with MD5. Both MD5 and SHA-1 have known collision weaknesses.
- The build executes dependency build scripts, installed host tools, Python build backends, GitHub Actions and Homebrew programs. Floating action tags, Python wheels without a hash lock, cached executables, and a rolling runner/tool selection all contribute to the installed app. The SHA-256 printed for the IPA identifies the produced bytes. It cannot establish the provenance of those inputs.
- I found no analytics SDK, telemetry destination, startup beacon, LAN listener or automatic fetch-and-execute path in the **original** iOS GHOST, creator entry or product plist. The simulator extension-install test **does download and enable remote Python**. The farm worker added in this change deliberately creates another execution path, available to a holder of the owner's farm credential.

## Build inputs

`build_files/ios/dependency_manifest.py` walks an existing prefix, hashes each file with SHA-256 and invokes local `file`, `lipo` and ABI inspection tools. It downloads nothing. There is no pretrusted manifest or signature comparison. `configure_dependencies.py` reads local Git/tool/SDK information and invokes CMake. Its cache key includes the hash of the versions file and iOS recipes. Its donor SHA is recorded as metadata. Neither script fetches a donor checkout. CMake performs the archive downloads during configuration.

`build_files/ios/build_environment/CMakeLists.txt` prefers the iOS recipe and falls back to `build_files/build_environment/cmake`. Both download lists have 123 entries. Without an allowlist the local wrapper checks all 123, even entries for other platforms. The preview selects the 64 marked below only on a dependency-cache miss. New downloads use CMake `EXPECTED_HASH` and `TLS_VERIFY ON`. The mirror path rehashes existing packages. In upstream mode cached archives can skip the configure-time rehash unless `FORCE_CHECK_HASH` is on. ExternalProject recipes generally verify the local archive again using `URL_HASH`.

### CI and host tooling

“Repo SHA-256” means an expected digest fixed by this source revision and checked against downloaded bytes. A service signature, Git revision, version constraint or cache lookup key gives a different guarantee. Service-generated and redirected URLs are identified by their resolver where the final URL is unavailable offline.

| Input | URL or URL resolver | Repo SHA-256 |
|---|---|---|
| Workflow code | `https://github.com/actions/checkout` at `v6`, `https://github.com/actions/setup-python` at `v6`, `https://github.com/actions/cache` restore and save at `v5` | No. All are moving major-version tags. |
| PR checkout | `https://github.com/Shlok-Bhakta/3d-modeling-thingy-ios.git` for this origin, or `https://github.com/<owner>/<repo>.git` in the owner's fork | No. The event selects a Git revision, normally the PR merge ref for checkout. The release step uses the PR head SHA. |
| Asset, data and script hydration | `https://projects.blender.org/blender/blender.git/info/lfs/objects/batch` returns the individual object download URLs | Yes, via each committed LFS pointer's SHA-256 OID. The filter covers `assets/**`, `release/datafiles/**`, `release/ios/**`, `scripts/**`. 219 pointer paths in this revision. |
| Native build libraries on host-tools cache miss | `https://projects.blender.org/blender/lib-macos_arm64.git` and its `/info/lfs/objects/batch` endpoint | Git checkout uses gitlink `15fb54980d88e6e1a19ae050faf5fbbd1db6364c`. Individual LFS payloads have SHA-256 OIDs in that checkout. |
| Python build interpreter | `actions/setup-python` resolves `3.13` from the runner tool cache or the `https://github.com/actions/python-versions` manifest and its release assets | No. The patch release, installer filename and final CDN URL depend on the runner. |
| Apple Metal toolchain | `xcodebuild -downloadComponent MetalToolchain` resolves Apple's catalog and asset URL for Xcode 26.3 on the `macos-15` runner | No repo digest or literal asset URL. Apple controls component selection and signing. Xcode itself is selected from the runner. |
| Homebrew tooling | Homebrew's configured metadata and bottles, ordinarily `https://formulae.brew.sh/api/` and `https://ghcr.io/v2/homebrew/core/<formula>/`, with formula source URLs on fallback | No repo digests. Brew resolves formulae and transitive dependencies and checks the checksums in its own metadata. The workflow requests autoconf, automake, bison, ccache, dos2unix, flex, libtool, meson, ninja, pkgconf and yasm. |
| Actions caches | GitHub Actions cache service and its signed archive URLs supplied to the runner | No trusted payload digest in the workflow. Three restores cover the dependency prefix, native tools/dylibs, and ccache. Dependency hits check selected files and skip the cold-build ABI scan. Native hits check presence and architecture. The compiler cache permits a prefix fallback. |
| Release verification | `https://github.com/<owner>/<repo>/releases/download/pr-<number>/DevBlender-test.blenderfoundation.blender.ios-unsigned.ipa` | CI follows redirects with a HEAD request and checks content type. It hashes the local IPA. `gh` calls GitHub's API to read PRs, replace the prerelease, upload the IPA and comment. |
| Install link in the release | `https://marginally-better-apps.github.io/Autoloader/?url=<encoded-IPA-URL>` | No. CI constructs this third-party link. Opening it and on-device signing are separate from building the app. |

The workflow gates on non-draft, same-repository PRs with selected branch prefixes. It grants contents and PR write permissions and exports `GH_TOKEN` at job scope while building PR-controlled code. A writer who can change such a PR or its build inputs has a path to release publication credentials. Downloaded cached native helpers execute with their associated dylibs via `DYLD_LIBRARY_PATH`.

The optional upstream macOS host bootstrap in `build_files/build_environment/macos/macos_setup.sh` runs a downloaded shell script from `https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh` when Homebrew is missing. There is no repository digest. It can select/install a local Xcode XIP, points the operator at `https://developer.apple.com/services-account/download?path=/Developer_Tools/Xcode_26/Xcode_26.xip`, downloads Apple's Metal component, taps `https://github.com/Homebrew/homebrew-core` and resolves CMake 3.31.6 and Brew tools. The preview uses its own setup steps. Windows/MSYS2 and Linux provisioners in the shared tree are outside the iOS execution path. Optional `cve_check*` targets run the installed Grype scanner, whose database source and updates depend on its installation. The preview does not invoke them.

### Python package downloads

The cross-venv and target-site recipes use the configured pip index, normally `https://pypi.org/simple/<normalized-name>/`. Each index entry below resolves to a wheel or source URL, usually under `https://files.pythonhosted.org/packages/`. **None has a SHA-256 pin from this repo in the pip command.** Pip can check the digest advertised by the same live index. An alternate pip index or cache can supply the bytes. Target site packages use `--no-deps --only-binary=:all:`. The cross-venv install allows resolver dependencies. Its installed Cython, setuptools and meson frontends execute on the build host. NumPy and zstandard wheel builds use checked local sources with `--no-build-isolation --no-deps`, then install their produced wheels with `--no-index`.

| Package | Version | Used by | Index URL |
|---|---|---|---|
| Cython | 3.0.11 | Build venv | `https://pypi.org/simple/cython/` |
| attrs | 25.3.0 | Target | `https://pypi.org/simple/attrs/` |
| autopep8 | 2.3.1 | Target | `https://pypi.org/simple/autopep8/` |
| cattrs | 25.1.1 | Target | `https://pypi.org/simple/cattrs/` |
| certifi | 2026.10.19 | Target | `https://pypi.org/simple/certifi/` |
| charset-normalizer | 3.4.1 | Target | `https://pypi.org/simple/charset-normalizer/` |
| docutils | 0.22.4 | Target | `https://pypi.org/simple/docutils/` |
| idna | 3.10 | Target | `https://pypi.org/simple/idna/` |
| meson | 1.9.0 | Build venv, Target | `https://pypi.org/simple/meson/` |
| meson-python | 0.18.0 | Build venv, Target | `https://pypi.org/simple/meson-python/` |
| packaging | 25.0 | Build venv, Target | `https://pypi.org/simple/packaging/` |
| pycodestyle | 2.13 | Target | `https://pypi.org/simple/pycodestyle/` |
| pyproject-metadata | 0.9.1 | Build venv, Target | `https://pypi.org/simple/pyproject-metadata/` |
| requests | 2.32.3 | Target | `https://pypi.org/simple/requests/` |
| setuptools | 80.9.0 | Build venv, Target | `https://pypi.org/simple/setuptools/` |
| tomli-w | 1.2.0 | Target | `https://pypi.org/simple/tomli-w/` |
| typing-extensions | 4.14.1 | Target | `https://pypi.org/simple/typing-extensions/` |
| urllib3 | 2.4.0 | Target | `https://pypi.org/simple/urllib3/` |

The target recipe also writes a setuptools-scm 9.2.2 constraint. A constraint alone does not request a download. Index queries such as pip's own version check can depend on pip's configuration. The exact transitive artifacts, Homebrew bottles, Apple component CDN URLs and GitHub service redirects require a resolved build or network log.

## Original iOS runtime and test harnesses

| Surface inspected | Network or execution found |
|---|---|
| `intern/ghost` iOS system, window, paths, Metal, file access, input and settings shims | UIKit open-document callbacks reject non-file URLs. Document pickers and settings use Foundation file APIs and security-scoped URLs. A Files provider may hydrate a user-selected file through iOS. No app-owned network endpoint was found in these paths. |
| `source/creator/creator.cc`, argument handling and the GHOST iOS callback | UIKit starts the ordinary Blender entry point with launch arguments. Generic `--python`, `--python-text`, `--addons` and `--python-expr` can execute caller-selected code. The original entry point contains no network command listener. Crash reporting here writes local files. |
| `release/ios/Blender.app` | Plist metadata registers .blend documents, file sharing and opening in place. The Apple DTD URL is an XML identifier. No tracker, embedded script or remote start URL was found. |
| `build_files/ios/simulator_extensions.py` and the bundled extension manager | The harness explicitly launches with `--online-mode`, syncs repositories, chooses the smallest compatible pure-Python add-on in the live Blender index, installs it with `enable_on_install=True`, then uninstalls it. The default repo is `https://extensions.blender.org/api/v1/extensions/`. The archive URL and SHA-256 come from the live index. The test pins neither the selected package nor its digest locally. Enabling it executes code. Other enabled repos may also be synced. |
| `build_files/ios/simulator_file_access.py` and `maestro/file_access.yaml` | A host-only HTTP fixture binds `127.0.0.1` on an ephemeral port. Maestro requests `http://127.0.0.1:<port>/after-close` for liveness. Simulator harnesses inject repository-supplied Python via launch arguments. File-access and compute-failure probes build and load local dylibs. The hardware-input probe also sets `SIMCTL_CHILD_DYLD_INSERT_LIBRARIES`. These operations are test instrumentation. |
| `build_files/ios/simulator_gesture_probe.py` | When manually loaded on the documentation simulator, its timer reads, deletes and executes a writable `DEMO_DIRECTORY/command.py`. Anyone able to write that file can run Python in that simulator session. The probe has no socket and is outside the bundled startup scripts. |
| Other `build_files/ios` scripts, fixtures, tests, schemas, CMake recipes, asset/IPA packaging | Found local shell/tool invocations, test Python execution, document/schema identifiers, version-control/LFS identifiers and the build downloads inventoried here. No separate analytics or upload service in the packaging scripts. The preview workflow performs the GitHub publication. |
| Adjacent runtime shims | The Python import smoke in `bpy_interface_ios.hh` starts and stops the bundled HTTP downloader thread when explicitly enabled. It submits no URL. Its version assertions still name Blender 5.2. The Cycles smoke runs an embedded render script. Blender's shared HTTP downloader and extensions can make network requests for their normal features. On iOS extension commands can execute in-process. |

This review searched filenames and contents for URL schemes, UIKit/Foundation/CFNetwork clients, socket operations, Python HTTP clients, reporting SDKs, fetch/install/execute paths and simulator injection. It followed matches to their call sites. Third-party source archives, binaries in remotely restored caches and OS activity are outside this static review.

## Running the owner build

The iOS creator already installs `scripts/` into `Blender.app/Assets/5.3/scripts/`. The bundled add-on is `scripts/addons_core/farm_worker/`. Ordinary launch with no worker configuration leaves the socket closed. There is no baked-in credential or discovery broadcast.

1. Configure the existing device build with `-DBLENDER_IOS_BUNDLE_ID=com.example.studio.farm` and `-DBLENDER_IOS_APP_NAME="Studio Farm"`, substituting the owner's registered identifier. These drive the app plist, Xcode product identity and packaged Python extension framework IDs. The device presets default to unsigned and accept explicit Xcode signing settings. For signing after staging, use the completed installed bundle. The unsigned IPA packager accepts `--bundle-id com.example.studio.farm`. The public PR preview's separate sideload packager deliberately applies its preview branding.
2. Put the farm server's high-entropy secret in a UTF-8 file such as `Documents/farm.token`. Give each independently trusted worker or farm its own secret. Keep the value out of command arguments. The server URL in the examples is a placeholder.
3. Launch through devicectl, or save the equivalent JSON in the app's Documents and open the app. Relative token and CA paths resolve from Documents. Explicit launch options override corresponding JSON values. The default MCP port is 9876.

```sh
xcrun devicectl device process launch --device "$DEVICE" com.example.studio.farm -- \
  --farm-worker https://farm.example:8443 farm.token --mcp-port 9876
```

```json
{"server_url":"https://farm.example:8443","token_file":"farm.token","mcp_port":9876}
```

For a private farm CA, add `"ca_file":"farm-ca.pem"` and provision that PEM in Documents. Farm polling verifies HTTPS certificates and hostnames. Plain HTTP is accepted only for the numeric loopback addresses used by a local fixture. The token is part of the requested URL path by protocol, so farm and reverse-proxy access logs must treat the path as a secret. The worker connects directly to the configured origin without following redirects.

While the worker is active in the foreground, the app disables UIKit's idle timer. Disabling the add-on restores the previous value. iOS can still suspend a backgrounded app. Remove the configuration and launch flags to return to ordinary startup.

### MCP and command line

A one-shot command from the Mac reads a normal Blender MCP object from stdin. For the existing Blender MCP client, start the foreground bridge on the trusted Mac and point the existing client at `127.0.0.1:9876`. Set `--port` to select a different device port. Only the bridge's local port is set by `--bridge`.

```sh
echo '{"type":"get_object_info","params":{"name":"Cube"}}' | \
  python3 tools/farm_worker_client.py ipad.local ./farm.token

python3 tools/farm_worker_client.py ipad.local ./farm.token --bridge 9876
```

The bridge accepts the stock, unframed UTF-8 JSON request/response sequence and returns the usual `status` and `result` or `message`. It supports `get_scene_info`, `get_object_info` with `name`, `execute_code` with `code`, and `render` with optional absolute device `filepath`. The render response contains the final path. Optional asset-service status probes report disabled. The bridge grants processes on that Mac access while it runs. It binds only to loopback.

The device listens on the selected TCP port using IPv4 and IPv6 where dual-stack sockets are available, with an IPv4 fallback. For each command the Mac requests a new 256-bit challenge on the same connection. HMAC-SHA-256 authenticates the entire request and reply using the farm token, distinct direction labels and canonical JSON. The server consumes the challenge once. Stock requests sent straight to the device receive an authentication error. The token never travels over MCP. Scene data, commands and results on that socket are visible to network observers. Use a private LAN or an encrypted network when their contents are sensitive. The codec is in `farm_worker/protocol.py`.

### Farm server contract

No existing piece or result schema was present in this copy. The implemented HTTP contract uses the following paths relative to `<server-url>/<percent-encoded-token>`.

| Request | Contract |
|---|---|
| `GET /next?runtime=blender` | Return 204 for idle, or 200 with the JSON piece below. The JSON limit is 64 MiB including encoded inputs. IDs use 1–128 ASCII letters, digits, underscores or hyphens. |
| `PUT /pieces/<id>/files/<relative-path>` | Raw bytes and Content-Length. Each regular output file is streamed, including nested files. Accept duplicate PUTs by replacing the same object. |
| `POST /pieces/<id>/complete` | JSON `{"status":"success"}` or `{"status":"error","message":"..."}`. Return 2xx for an accepted or already-recorded completion. |

```json
{"id":"tile_1","files":{"seed.txt":"Y3ViZQ=="},"script":"(output_dir / 'result.txt').write_text((input_dir / 'seed.txt').read_text() + ':' + bpy.context.scene.name)"}
```

Each piece gets fresh input and output directories. `files` maps relative names to base64 bytes. The script receives `bpy`, `input_dir` and `output_dir` in the current Blender process. Ordinary relative writes during a script step go to the output directory. Only regular files below that directory are uploaded. The worker rejects traversal in inputs, and links or special files in outputs. These directories organize transfers. **Authenticated Python has the full permissions of the Blender process**, including its accessible files and network. Blender scene changes persist across jobs.

Network threads handle poll, parsing, transfer and retry. A persistent Blender timer advances one command at a time on the main thread. The interactive render command uses Blender's asynchronous render operator. For lengthy Python pieces or MCP scripts, define a `farm_steps()` generator and yield between bounded batches. Each yield returns control to Blender's event loop. An arbitrary synchronous Python statement, blocking I/O inside a submitted script, or a long synchronous bpy operator can still stall the UI. Blender cannot preempt those calls on its main thread.

A transfer retry reuses the existing output without rerunning the script. The next poll follows the completion acknowledgement. An interrupted app has no durable job journal. The server should lease pieces, handle repeated results idempotently and only reissue work that is safe to run again.


## Verification on this Mac

- Desktop binary `/Applications/Blender.app/Contents/MacOS/Blender`, version **5.3.0**, revision `02f0899d78e3`. The test launches it with `--background --factory-startup --python` and places its config, TLS fixture and output under a temporary directory in `src/.tmp/`.
- `python3 tools/farm_worker_test.py --socketpair` passed with the stock JSON messages through the bridge, missing/incorrect credentials and replay rejection, scene and object inspection, an actual cube edit, and a 16 × 16 Cycles CPU PNG. One HTTPS piece read an input, yielded to another Blender timer and uploaded the expected output bytes. The server returned 503 once. The worker retried the upload, acknowledged completion and polled again. The harness pumps Blender's native timer scheduler because background Blender returns when its startup script exits.
- `python3 tools/farm_worker_test.py` uses real TCP loopback on a normal Mac. Here the OS sandbox denied the test server's IPv4 bind with `EPERM`. Connected local sockets exercised the codec, certificate-checked TLS, HTTP, add-on and Blender timer in the passing run. Actual TCP reachability, the iOS LAN permission dialog and physical screen-awake behavior remain unverified.
- Both changed GHOST Objective-C++ units and the embedded Python interface unit compiled to arm64 iOS objects. The isolated Python-interface compile used locally installed CPython 3.13 headers. A Mac Catalyst fixture ran the real native argument shim with and without a separator and checked ordinary startup. A minimal device bundle using the product's actual CMake plist hook produced the custom ID and an XML-escaped display name and passed the unsigned IPA packager with `--bundle-id`. No full iOS Blender app was built, signed or installed.
- `python3 -m unittest discover -s build_files/ios/tests` ran 366 tests. 364 passed. The configure-plan test requires the mounted `/Volumes/BlenderBuild` volume. The port-map test requires the absent `v5.1.2..a1de44dd54af75a4c8c4a29a5fed2a1334a87446` Git history.

## Archive inventory

Each mirror filename below links to its full URL on the 5.3 release branch. The local default URL and digest are expanded from `build_files/build_environment/cmake/versions.cmake`. The digest applies to either origin. Every MD5 or SHA-1 entry has **no SHA-256 pin**. Across the full list, 60 entries use SHA-256, 62 use MD5 and one uses SHA-1.

| Dependency | Preview | Mirror URL | Upstream URL | Expected algorithm and digest |
|---|---|---|---|---|
| ZLIB | Yes | [zlib-1.3.1.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/zlib-1.3.1.tar.gz) | `https://github.com/madler/zlib/releases/download/v1.3.1/zlib-1.3.1.tar.gz` | MD5 `9855b6d802d7fe5b7bd5b196a2271655` |
| OPENAL | Yes | [openal-soft-1.23.1.tar.bz2](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/openal-soft-1.23.1.tar.bz2) | `https://github.com/kcat/openal-soft/releases/download/1.23.1/openal-soft-1.23.1.tar.bz2` | MD5 `58a73698288d2787451b61f8f4431513` |
| PNG | Yes | [libpng-1.6.58.tar.xz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/libpng-1.6.58.tar.xz) | `http://prdownloads.sourceforge.net/libpng/libpng-1.6.58.tar.xz` | SHA256 `28eb403f51f0f7405249132cecfe82ea5c0ef97f1b32c5a65828814ae0d34775` |
| JPEG | Yes | [libjpeg-turbo-2.1.3.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/libjpeg-turbo-2.1.3.tar.gz) | `https://github.com/libjpeg-turbo/libjpeg-turbo/archive/2.1.3.tar.gz` | MD5 `627b980fad0573e08e4c3b80b290fc91` |
| BLOSC | Yes | [blosc-1.21.1.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/blosc-1.21.1.tar.gz) | `https://github.com/Blosc/c-blosc/archive/v1.21.1.tar.gz` | MD5 `134b55813b1dca57019d2a2dc1f7a923` |
| PTHREADS | — | [pthreads4w-code-3.0.0.zip](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/pthreads4w-code-3.0.0.zip) | `http://prdownloads.sourceforge.net/pthreads4w/pthreads4w-code-v3.0.0.zip` | MD5 `f3bf81bb395840b3446197bcf4ecd653` |
| OPENEXR | Yes | [openexr-3.4.10.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/openexr-3.4.10.tar.gz) | `https://github.com/AcademySoftwareFoundation/openexr/archive/v3.4.10.tar.gz` | MD5 `8926ba09c4e4cd21c7a0fa2d2b39fa82` |
| FREETYPE | Yes | [freetype-2.13.3.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/freetype-2.13.3.tar.gz) | `http://prdownloads.sourceforge.net/freetype/freetype-2.13.3.tar.gz` | MD5 `ac1f0b517f62bd40d50bc995faa5741d` |
| EPOXY | — | [libepoxy-1.5.10.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/libepoxy-1.5.10.tar.gz) | `https://github.com/anholt/libepoxy/archive/refs/tags/1.5.10.tar.gz` | MD5 `f0730aad115c952e77591fcc805b1dc1` |
| ALEMBIC | Yes | [alembic-1.8.3.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/alembic-1.8.3.tar.gz) | `https://github.com/alembic/alembic/archive/1.8.3.tar.gz` | MD5 `2cd8d6e5a3ac4a014e24a4b04f4fadf9` |
| OPENSUBDIV | Yes | [opensubdiv-v3_7_0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/opensubdiv-v3_7_0.tar.gz) | `https://github.com/PixarAnimationStudios/OpenSubdiv/archive/v3_7_0.tar.gz` | MD5 `470d53c4d4335a601c33a052ce7c33b4` |
| SDL | — | [SDL3-3.4.2.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/SDL3-3.4.2.tar.gz) | `https://github.com/libsdl-org/SDL/releases/download/release-3.4.2/SDL3-3.4.2.tar.gz` | MD5 `b488ea1ede947c06855588314effe905` |
| OPENCOLORIO | Yes | [OpenColorIO-2.5.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/OpenColorIO-2.5.0.tar.gz) | `https://github.com/AcademySoftwareFoundation/OpenColorIO/archive/v2.5.0.tar.gz` | MD5 `41d6b62ac672ed333ebfdcc1108407e0` |
| MINIZIPNG | Yes | [minizip-ng-4.2.2.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/minizip-ng-4.2.2.tar.gz) | `https://github.com/zlib-ng/minizip-ng/archive/4.2.2.tar.gz` | MD5 `18f641a533be10efe89a8429197ff662` |
| LLVM | — | [llvm-project-22.1.7.src.tar.xz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/llvm-project-22.1.7.src.tar.xz) | `https://github.com/llvm/llvm-project/releases/download/llvmorg-22.1.7/llvm-project-22.1.7.src.tar.xz` | MD5 `19edd1ed7dbb9d82e160da434ea8972a` |
| OPENIMAGEIO | Yes | [OpenImageIO-v3.1.16.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/OpenImageIO-v3.1.16.0.tar.gz) | `https://github.com/AcademySoftwareFoundation/OpenImageIO/archive/refs/tags/v3.1.16.0.tar.gz` | MD5 `34e4f68d174c6768ce1d035d6f2f072f` |
| TIFF | Yes | [tiff-4.7.1.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/tiff-4.7.1.tar.gz) | `http://download.osgeo.org/libtiff/tiff-4.7.1.tar.gz` | MD5 `f1044dd3b4466cc53464210148e08146` |
| OSL | — | [OpenShadingLanguage-1.15.6.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/OpenShadingLanguage-1.15.6.0.tar.gz) | `https://github.com/AcademySoftwareFoundation/OpenShadingLanguage/archive/refs/tags/v1.15.6.0.tar.gz` | SHA256 `85b71407ad28c464a7ec5c9dcb33ac67f9e98b92495568549d4b9c138c91a579` |
| PYTHON | Yes | [Python-3.13.13.tar.xz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/Python-3.13.13.tar.xz) | `https://www.python.org/ftp/python/3.13.13/Python-3.13.13.tar.xz` | MD5 `3a19dd420883dd599728c9dd07c141e7` |
| TBB | Yes | [oneTBB-v2022.3.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/oneTBB-v2022.3.0.tar.gz) | `https://github.com/uxlfoundation/oneTBB/archive/refs/tags/v2022.3.0.tar.gz` | MD5 `2b242c465b194ac8e1451ea1354873ae` |
| OPENVDB | Yes | [openvdb-13.0.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/openvdb-13.0.0.tar.gz) | `https://github.com/AcademySoftwareFoundation/openvdb/archive/v13.0.0.tar.gz` | MD5 `7a10f529ed12d9e3ed6d3fd50f157378` |
| CYTHON | — | [cython-3.0.11.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/cython-3.0.11.tar.gz) | `https://github.com/cython/cython/releases/download/3.0.11-1/cython-3.0.11.tar.gz` | MD5 `388b85b7c23f501320d19d991b169f5d` |
| ZSTANDARD | Yes | [zstandard-0.25.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/zstandard-0.25.0.tar.gz) | `https://github.com/indygreg/python-zstandard/releases/download/0.25.0/zstandard-0.25.0.tar.gz` | SHA256 `7713e1179d162cf5c7906da876ec2ccb9c3a9dcbdffef0cc7f70c3667a205f0b` |
| NUMPY | Yes | [numpy-2.3.4.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/numpy-2.3.4.tar.gz) | `https://github.com/numpy/numpy/releases/download/v2.3.4/numpy-2.3.4.tar.gz` | MD5 `8717ed1828a8a390c454c6636e91c46a` |
| LAME | Yes | [lame-3.100.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/lame-3.100.tar.gz) | `http://downloads.sourceforge.net/project/lame/lame/3.100/lame-3.100.tar.gz` | MD5 `83e260acbe4389b54fe08e0bdbf7cddb` |
| OGG | Yes | [libogg-1.3.5.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/libogg-1.3.5.tar.gz) | `http://downloads.xiph.org/releases/ogg/libogg-1.3.5.tar.gz` | SHA256 `0eb4b4b9420a0f51db142ba3f9c64b333f826532dc0f48c6410ae51f4799b664` |
| VORBIS | Yes | [libvorbis-1.3.7.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/libvorbis-1.3.7.tar.gz) | `http://downloads.xiph.org/releases/vorbis/libvorbis-1.3.7.tar.gz` | SHA256 `0e982409a9c3fc82ee06e08205b1355e5c6aa4c36bca58146ef399621b0ce5ab` |
| THEORA | Yes | [libtheora-1.1.1.tar.bz2](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/libtheora-1.1.1.tar.bz2) | `http://downloads.xiph.org/releases/theora/libtheora-1.1.1.tar.bz2` | SHA256 `b6ae1ee2fa3d42ac489287d3ec34c5885730b1296f0801ae577a35193d3affbc` |
| FLAC | Yes | [flac-1.5.0.tar.xz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/flac-1.5.0.tar.xz) | `http://downloads.xiph.org/releases/flac/flac-1.5.0.tar.xz` | SHA256 `f2c1c76592a82ffff8413ba3c4a1299b6c7ab06c734dee03fd88630485c2b920` |
| VPX | Yes | [libvpx-v1.15.2.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/libvpx-v1.15.2.tar.gz) | `https://github.com/webmproject/libvpx/archive/v1.15.2/libvpx-v1.15.2.tar.gz` | SHA256 `26fcd3db88045dee380e581862a6ef106f49b74b6396ee95c2993a260b4636aa` |
| OPUS | Yes | [opus-1.3.1.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/opus-1.3.1.tar.gz) | `https://archive.mozilla.org/pub/opus/opus-1.3.1.tar.gz` | SHA256 `65b58e1e25b2a114157014736a3d9dfeaad8d41be1c8179866f144a2fb44ff9d` |
| X264 | — | [x264-35fe20d1ba49918ec739a5b068c208ca82f977f7.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/x264-35fe20d1ba49918ec739a5b068c208ca82f977f7.tar.gz) | `https://code.videolan.org/videolan/x264/-/archive/35fe20d1ba49918ec739a5b068c208ca82f977f7/x264-35fe20d1ba49918ec739a5b068c208ca82f977f7.tar.gz` | SHA256 `bb4f7da03936b5a030ed5827133b58eb3f701d7e5dce32cca4ba6df93797d42e` |
| X265 | — | [x265-4.1.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/x265-4.1.tar.gz) | `https://bitbucket.org/multicoreware/x265_git/downloads/x265_4.1.tar.gz` | SHA256 `a31699c6a89806b74b0151e5e6a7df65de4b49050482fe5ebf8a4379d7af8f29` |
| OPENJPEG | Yes | [openjpeg-v2.5.3.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/openjpeg-v2.5.3.tar.gz) | `https://github.com/uclouvain/openjpeg/archive/v2.5.3.tar.gz` | SHA256 `368fe0468228e767433c9ebdea82ad9d801a3ad1e4234421f352c8b06e7aa707` |
| FFMPEG | Yes | [ffmpeg-8.1.tar.bz2](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/ffmpeg-8.1.tar.bz2) | `http://ffmpeg.org/releases/ffmpeg-8.1.tar.bz2` | SHA256 `c07039598df7d64d3c8b42c4e25b1959fc908621c6f6c2946881133f3b27eda2` |
| FFNVCODEC | — | [nv-codec-headers-n12.1.14.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/nv-codec-headers-n12.1.14.0.tar.gz) | `https://github.com/FFmpeg/nv-codec-headers/archive/n12.1.14.0.tar.gz` | SHA256 `2fefaa227d2a3b4170797796425a59d1dd2ed5fd231db9b4244468ba327acd0b` |
| AMF | — | [AMF-v1.5.2.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/AMF-v1.5.2.tar.gz) | `https://github.com/GPUOpen-LibrariesAndSDKs/AMF/archive/refs/tags/v1.5.2.tar.gz` | SHA256 `8a70b6dc85261e6e6e57769bd81ac1e09c0a4c96bbd5e358ffbc2dee51e8e50a` |
| FFTW | Yes | [fftw-3.3.10.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/fftw-3.3.10.tar.gz) | `http://www.fftw.org/fftw-3.3.10.tar.gz` | MD5 `8ccbf6a5ea78a16dbc3e1306e234cc5c` |
| SNDFILE | Yes | [libsndfile-1.2.2.tar.xz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/libsndfile-1.2.2.tar.xz) | `https://github.com/libsndfile/libsndfile/releases/download/1.2.2/libsndfile-1.2.2.tar.xz` | MD5 `04e2e6f726da7c5dc87f8cf72f250d04` |
| WEBP | Yes | [libwebp-1.6.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/libwebp-1.6.0.tar.gz) | `https://storage.googleapis.com/downloads.webmproject.org/releases/webp/libwebp-1.6.0.tar.gz` | MD5 `cceb6447180f961473b181c9ef38b630` |
| SPNAV | — | [libspnav-1.1.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/libspnav-1.1.tar.gz) | `https://github.com/FreeSpacenav/libspnav/releases/download/v1.1/libspnav-1.1.tar.gz` | MD5 `7c0032034672dfba3c4bb9b49a440e70` |
| XML2 | — | [libxml2-2.14.6.tar.xz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/libxml2-2.14.6.tar.xz) | `https://download.gnome.org/sources/libxml2/2.14/libxml2-2.14.6.tar.xz` | MD5 `a2bb2b6cb8fc7be1fafa14f500e4f7c5` |
| YAMLCPP | Yes | [yaml-cpp-0.8.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/yaml-cpp-0.8.0.tar.gz) | `https://github.com/jbeder/yaml-cpp/archive/refs/tags/0.8.0.tar.gz` | MD5 `1d2c7975edba60e995abe3c4af6480e5` |
| EXPAT | Yes | [libexpat-2_7_5.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/libexpat-2_7_5.tar.gz) | `https://github.com/libexpat/libexpat/archive/R_2_7_5.tar.gz` | MD5 `aecc4366ab1a5189d8f027c369305c9a` |
| PUGIXML | Yes | [pugixml-1.10.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/pugixml-1.10.tar.gz) | `https://github.com/zeux/pugixml/archive/v1.10.tar.gz` | MD5 `0c208b0664c7fb822bf1b49ad035e8fd` |
| FLEXBISON | — | [win_flex_bison-2.5.24.zip](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/win_flex_bison-2.5.24.zip) | `http://prdownloads.sourceforge.net/winflexbison/win_flex_bison-2.5.24.zip` | MD5 `6b549d43e34ece0e8ed05af92daa31c4` |
| BZIP2 | Yes | [bzip2_1.0.8.orig.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/bzip2_1.0.8.orig.tar.gz) | `http://http.debian.net/debian/pool/main/b/bzip2/bzip2_1.0.8.orig.tar.gz` | SHA256 `ab5a03176ee106d3f0fa90e381da478ddae405918153cca248e682cd0c4a2269` |
| FFI | Yes | [libffi-3.5.2.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/libffi-3.5.2.tar.gz) | `https://github.com/libffi/libffi/releases/download/v3.5.2/libffi-3.5.2.tar.gz` | SHA256 `f3a3082a23b37c293a4fcd1053147b371f2ff91fa7ea1b2a52e335676bac82dc` |
| LZMA | Yes | [xz-5.2.5.tar.bz2](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/xz-5.2.5.tar.bz2) | `https://tukaani.org/xz/xz-5.2.5.tar.bz2` | SHA256 `5117f930900b341493827d63aa910ff5e011e0b994197c3b71c08a20228a42df` |
| SSL | Yes | [openssl-3.5.6.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/openssl-3.5.6.tar.gz) | `https://www.openssl.org/source/openssl-3.5.6.tar.gz` | SHA256 `deae7c80cba99c4b4f940ecadb3c3338b13cb77418409238e57d7f31f2a3b736` |
| SQLITE | Yes | [sqlite-autoconf-3510300.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/sqlite-autoconf-3510300.tar.gz) | `https://www.sqlite.org/2026/sqlite-autoconf-3510300.tar.gz` | SHA1 `d917ad1cde07987643571f0f5b55dd954fa8dee3` |
| EMBREE | Yes | [embree-v4.4.1.zip](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/embree-v4.4.1.zip) | `https://github.com/RenderKit/embree/archive/v4.4.1.zip` | MD5 `6e2eecafb312d8cf1f1ff555702637cf` |
| USD | Yes | [usd-v26.08.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/usd-v26.08.tar.gz) | `https://github.com/PixarAnimationStudios/OpenUSD/archive/v26.08.tar.gz` | MD5 `333b9530b83bf74036af45d25bdaa4a0` |
| MATERIALX | Yes | [materialx-v1.39.4.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/materialx-v1.39.4.tar.gz) | `https://github.com/AcademySoftwareFoundation/MaterialX/archive/refs/tags/v1.39.4.tar.gz` | MD5 `4704716b93e4c2d6b3693aa56a13b71b` |
| OIDN | Yes | [oidn-2.5.0.src.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/oidn-2.5.0.src.tar.gz) | `https://github.com/RenderKit/oidn/releases/download/v2.5.0/oidn-2.5.0.src.tar.gz` | MD5 `ae984ce4cc4c81ec152ab81b241a8738` |
| NASM | — | [nasm-2.15.02.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/nasm-2.15.02.tar.gz) | `https://github.com/netwide-assembler/nasm/archive/nasm-2.15.02.tar.gz` | SHA256 `aded8b796c996a486a56e0515c83e414116decc3b184d88043480b32eb0a8589` |
| XR_OPENXR_SDK | — | [OpenXR-SDK-1.1.53.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/OpenXR-SDK-1.1.53.tar.gz) | `https://github.com/KhronosGroup/OpenXR-SDK/archive/release-1.1.53.tar.gz` | MD5 `e2e1b25fd480947ddc2f2c68423d47e5` |
| WL_PROTOCOLS | — | [wayland-protocols-1.44.tar.xz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/wayland-protocols-1.44.tar.xz) | `https://gitlab.freedesktop.org/wayland/wayland-protocols/-/releases/1.44/downloads/wayland-protocols-1.44.tar.xz` | MD5 `bbf053c2d62cf11e253cf2cc151c2df0` |
| WAYLAND | — | [wayland-1.24.0.tar.xz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/wayland-1.24.0.tar.xz) | `https://gitlab.freedesktop.org/wayland/wayland/-/releases/1.24.0/downloads/wayland-1.24.0.tar.xz` | MD5 `fda0b2a73ea2716f61d75767e02008e1` |
| WAYLAND_WESTON | — | [weston-14.0.2.tar.xz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/weston-14.0.2.tar.xz) | `https://gitlab.freedesktop.org/wayland/weston/-/releases/14.0.2/downloads/weston-14.0.2.tar.xz` | MD5 `4575a052e2ff3ea7819cfbf33868f8f5` |
| ISPC | — | [ispc-v1.30.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/ispc-v1.30.0.tar.gz) | `https://github.com/ispc/ispc/archive/v1.30.0.tar.gz` | MD5 `97efadfb848ef585b8f02cebd9da93e7` |
| GMP | Yes | [gmp-6.3.0.tar.xz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/gmp-6.3.0.tar.xz) | `https://gmplib.org/download/gmp/gmp-6.3.0.tar.xz` | MD5 `956dc04e864001a9c22429f761f2c283` |
| POTRACE | Yes | [potrace-1.16.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/potrace-1.16.tar.gz) | `http://potrace.sourceforge.net/download/1.16/potrace-1.16.tar.gz` | MD5 `5f0bd87ddd9a620b0c4e65652ef93d69` |
| HARU | Yes | [libharu-2.4.5.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/libharu-2.4.5.tar.gz) | `https://github.com/libharu/libharu/archive/refs/tags/v2.4.5.tar.gz` | MD5 `d5633fb741079a7675bb3e9e8e8a58ce` |
| ZSTD | Yes | [zstd-1.5.7.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/zstd-1.5.7.tar.gz) | `https://github.com/facebook/zstd/releases/download/v1.5.7/zstd-1.5.7.tar.gz` | SHA256 `eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3` |
| SSE2NEON | — | [sse2neon-227cc413fb2d50b2a10073087be96b59d5364aea.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/sse2neon-227cc413fb2d50b2a10073087be96b59d5364aea.tar.gz) | `https://github.com/DLTcollab/sse2neon/archive/227cc413fb2d50b2a10073087be96b59d5364aea.tar.gz` | SHA256 `3427a495743bb6fd1b5f9f806b80f57d67b1ac7ccf39a5f44aedd487fd7e6da1` |
| FLEX | — | [flex-2.6.4.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/flex-2.6.4.tar.gz) | `https://github.com/westes/flex/releases/download/v2.6.4/flex-2.6.4.tar.gz` | MD5 `2882e3179748cc9f9c23ec593d6adc8d` |
| BROTLI | Yes | [brotli-v1.0.10.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/brotli-v1.0.10.tar.gz) | `https://github.com/google/brotli/archive/refs/tags/v1.0.10.tar.gz` | SHA256 `b517ebdb5266b963d28d6e639b973479874ec72086deb6ee4a2d639e1b13606b` |
| FMT | Yes | [fmt-12.1.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/fmt-12.1.0.tar.gz) | `https://github.com/fmtlib/fmt/archive/refs/tags/12.1.0.tar.gz` | SHA256 `ea7de4299689e12b6dddd392f9896f08fb0777ac7168897a244a6d6085043fea` |
| ROBINMAP | Yes | [robinmap-v1.3.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/robinmap-v1.3.0.tar.gz) | `https://github.com/Tessil/robin-map/archive/refs/tags/v1.3.0.tar.gz` | SHA256 `a8424ad3b0affd4c57ed26f0f3d8a29604f0e1f2ef2089f497f614b1c94c7236` |
| IMATH | Yes | [imath-3.2.2.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/imath-3.2.2.tar.gz) | `https://github.com/AcademySoftwareFoundation/Imath/archive/v3.2.2.tar.gz` | MD5 `e29f25ce926ac53d8e0a52197299f61b` |
| PYSTRING | Yes | [pystring-v1.1.3.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/pystring-v1.1.3.tar.gz) | `https://codeload.github.com/imageworks/pystring/tar.gz/refs/tags/v1.1.3` | MD5 `f2c68786b359f5e4e62bed53bc4fb86d` |
| OPENPGL | Yes | [openpgl-v0.7.1.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/openpgl-v0.7.1.tar.gz) | `https://github.com/OpenPathGuidingLibrary/openpgl/archive/refs/tags/v0.7.1.tar.gz` | SHA256 `d62d24241232a526491328f341df9add274fc84ae9818470d3edb5ae6141ac63` |
| LEVEL_ZERO | — | [level-zero-v1.29.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/level-zero-v1.29.0.tar.gz) | `https://github.com/oneapi-src/level-zero/archive/v1.29.0.tar.gz` | SHA256 `c65a8d0944fbf762ea917d3094ef5f17c54a097cfb9e10f347dabafe50b2fe20` |
| DPCPP | — | [DPCPP-v7.1.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/DPCPP-v7.1.0.tar.gz) | `https://github.com/intel/llvm/archive/v7.1.0.tar.gz` | SHA256 `574cb3ebc34e253cea1e8acbf62a5bbaff4a46e6c125274c7101dfdeefce711d` |
| VCINTRINSICS | — | [vc-intrinsics-60cea7590bd022d95f5cf336ee765033bd114d69.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/vc-intrinsics-60cea7590bd022d95f5cf336ee765033bd114d69.tar.gz) | `https://github.com/intel/vc-intrinsics/archive/60cea7590bd022d95f5cf336ee765033bd114d69.tar.gz` | SHA256 `1cfd91a9178f1f8f01abca5815831ca7aa91d6b5e88cb77b6c7c71d1ff6982f4` |
| OPENCLHEADERS | — | [opencl_headers-v2025.07.22.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/opencl_headers-v2025.07.22.tar.gz) | `https://github.com/KhronosGroup/OpenCL-Headers/archive/v2025.07.22.tar.gz` | SHA256 `98f0a3ea26b4aec051e533cb1750db2998ab8e82eda97269ed6efe66ec94a240` |
| ICDLOADER | — | [icdloader-v2025.07.22.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/icdloader-v2025.07.22.tar.gz) | `https://github.com/KhronosGroup/OpenCL-ICD-Loader/archive/v2025.07.22.tar.gz` | SHA256 `dff7a0b11ad5b63a669358e3476e3dc889a4a361674e5b69b267b944d0794142` |
| EMHASH | — | [emhash-5e131ba09a5290823fe71099d9c35eb5df5345b6.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/emhash-5e131ba09a5290823fe71099d9c35eb5df5345b6.tar.gz) | `https://github.com/ktprime/emhash/archive/5e131ba09a5290823fe71099d9c35eb5df5345b6.tar.gz` | SHA256 `9cfa84367b4687b8ff662557362c48af883a6587657b6265e00061407c01ce68` |
| DPCPP_SPIRV_HEADERS | — | [DPCPP-SPIR-V-Headers-9268f3057354a2cb65991ba5f38b16d81e803692.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/DPCPP-SPIR-V-Headers-9268f3057354a2cb65991ba5f38b16d81e803692.tar.gz) | `https://github.com/KhronosGroup/SPIRV-Headers/archive/9268f3057354a2cb65991ba5f38b16d81e803692.tar.gz` | SHA256 `045027dfcc738b6d970c49b92bae30cdb22c30a9f3e8419c3d81921355004b94` |
| UNIFIED_MEMORY_FRAMEWORK | — | [unified-memory-framework-v1.1.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/unified-memory-framework-v1.1.0.tar.gz) | `https://github.com/oneapi-src/unified-memory-framework/archive/v1.1.0.tar.gz` | SHA256 `c08ec0e673f78b10b166c390aee50d83b3a99c666679f34d5b3a781b8f323dbd` |
| PARALLEL_HASHMAP | — | [parallel-hashmap-8a889d3699b3c09ade435641fb034427f3fd12b6.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/parallel-hashmap-8a889d3699b3c09ade435641fb034427f3fd12b6.tar.gz) | `https://github.com/greg7mdp/parallel-hashmap/archive/8a889d3699b3c09ade435641fb034427f3fd12b6.tar.gz` | SHA256 `da853a4a2cee32b1563391a3661cff3cf48af5e76e320c004d5520835eb9e5f6` |
| HWLOC | — | [hwloc-2.10.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/hwloc-2.10.0.tar.gz) | `https://github.com/open-mpi/hwloc/archive/refs/tags/hwloc-2.10.0.tar.gz` | SHA256 `9c5279b16b84c30e789b630568a62e9787d081f6b1932c9010f1e6db2b058489` |
| IGC | — | [intel-graphics-compiler-2.30.1.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/intel-graphics-compiler-2.30.1.tar.gz) | `https://github.com/intel/intel-graphics-compiler/archive/refs/tags/v2.30.1.tar.gz` | SHA256 `4e5f46b20ec5c055f3cbfed16cfa9739b67f0d05786d736f3d10b09b11b171a3` |
| IGC_LLVM | — | [llvmorg-16.0.6.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/llvmorg-16.0.6.tar.gz) | `https://github.com/llvm/llvm-project/archive/refs/tags/llvmorg-16.0.6.tar.gz` | SHA256 `56b2f75fdaa95ad5e477a246d3f0d164964ab066b4619a01836ef08e475ec9d5` |
| IGC_OPENCL_CLANG | — | [opencl-clang-v16.0.10.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/opencl-clang-v16.0.10.tar.gz) | `https://github.com/intel/opencl-clang/archive/v16.0.10.tar.gz` | SHA256 `24946cb5031d4a5fb8838d913d40724690b0fc455e0d21d00e6ada00824a4167` |
| IGC_VCINTRINSICS | — | [vc-intrinsics-0.25.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/vc-intrinsics-0.25.0.tar.gz) | `https://github.com/intel/vc-intrinsics/archive/refs/tags/v0.25.0.tar.gz` | SHA256 `83d6e0528feb6a47f7818e7c1dd3305dd8a48fb1103d279571dad517a93a8d39` |
| IGC_SPIRV_HEADERS | — | [SPIR-V-Headers-9268f3057354a2cb65991ba5f38b16d81e803692.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/SPIR-V-Headers-9268f3057354a2cb65991ba5f38b16d81e803692.tar.gz) | `https://github.com/KhronosGroup/SPIRV-Headers/archive/9268f3057354a2cb65991ba5f38b16d81e803692.tar.gz` | SHA256 `045027dfcc738b6d970c49b92bae30cdb22c30a9f3e8419c3d81921355004b94` |
| IGC_SPIRV_TOOLS | — | [SPIR-V-Tools-28a883ba4c67f58a9540fb0651c647bb02883622.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/SPIR-V-Tools-28a883ba4c67f58a9540fb0651c647bb02883622.tar.gz) | `https://github.com/KhronosGroup/SPIRV-Tools/archive/28a883ba4c67f58a9540fb0651c647bb02883622.tar.gz` | SHA256 `27c81a2f90dffdb18026bb62f455284c364ab25431df117816d55b9d944f880b` |
| IGC_SPIRV_TRANSLATOR | — | [SPIR-V-Translator-v16.0.10.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/SPIR-V-Translator-v16.0.10.tar.gz) | `https://github.com/KhronosGroup/SPIRV-LLVM-Translator/archive/v16.0.10.tar.gz` | SHA256 `6fd18c8aca59ccbc6809a0e4d159d8f2af82f6a6a46e85988737c6b2aaf459a6` |
| GMMLIB | — | [intel-gmmlib-22.8.1.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/intel-gmmlib-22.8.1.tar.gz) | `https://github.com/intel/gmmlib/archive/refs/tags/intel-gmmlib-22.8.1.tar.gz` | SHA256 `9b8eac1891650021ded26b72585e7a2c702a3ba47565c968feabd14ab38d18f7` |
| OCLOC | — | [ocloc-25.31.34666.3.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/ocloc-25.31.34666.3.tar.gz) | `https://github.com/intel/compute-runtime/archive/refs/tags/25.31.34666.3.tar.gz` | SHA256 `c307ec9d0296bcfa0bc4f93a9f0955d9a8ca479a00a731fda5a61eee3ed76489` |
| AOM | — | [libaom-3.13.1.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/libaom-3.13.1.tar.gz) | `https://storage.googleapis.com/aom-releases/libaom-3.13.1.tar.gz` | SHA256 `19e45a5a7192d690565229983dad900e76b513a02306c12053fb9a262cbeca7d` |
| FRIBIDI | — | [fribidi-v1.0.12.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/fribidi-v1.0.12.tar.gz) | `https://github.com/fribidi/fribidi/archive/refs/tags/v1.0.12.tar.gz` | SHA256 `2e9e859876571f03567ac91e5ed3b5308791f31cda083408c2b60fa1fe00a39d` |
| HARFBUZZ | — | [harfbuzz-10.0.1.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/harfbuzz-10.0.1.tar.gz) | `https://github.com/harfbuzz/harfbuzz/archive/refs/tags/10.0.1.tar.gz` | SHA256 `e7358ea86fe10fb9261931af6f010d4358dac64f7074420ca9bc94aae2bdd542` |
| SHADERC | — | [shaderc-v2025.4.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/shaderc-v2025.4.tar.gz) | `https://github.com/google/shaderc/archive/v2025.4.tar.gz` | MD5 `02208e374e610808c4ca3b1e7627b82d` |
| SHADERC_GLSLANG | — | [glslang-d213562e35573012b6348b2d584457c3704ac09b.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/glslang-d213562e35573012b6348b2d584457c3704ac09b.tar.gz) | `https://github.com/KhronosGroup/glslang/archive/d213562e35573012b6348b2d584457c3704ac09b.tar.gz` | MD5 `ac98b61f77ffade6bf819e342dc40c4c` |
| VULKAN_HEADERS | — | [Vulkan-Headers-1.4.341.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/Vulkan-Headers-1.4.341.tar.gz) | `https://github.com/KhronosGroup/Vulkan-Headers/archive/refs/tags/v1.4.341.tar.gz` | MD5 `57f17871ef2c43fc9ac01708a4bd3c82` |
| VULKAN_LOADER | — | [Vulkan-Loader-1.4.341.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/Vulkan-Loader-1.4.341.tar.gz) | `https://github.com/KhronosGroup/Vulkan-Loader/archive/refs/tags/v1.4.341.tar.gz` | MD5 `30c6850af7ed0e4af5c57002253c0138` |
| VULKAN_UTILITY_LIBRARIES | — | [Vulkan-Utility-Libraries-1.4.341.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/Vulkan-Utility-Libraries-1.4.341.tar.gz) | `https://github.com/KhronosGroup/Vulkan-Utility-Libraries/archive/refs/tags/v1.4.341.tar.gz` | MD5 `7b0980463b271b6e78269b3828841bb6` |
| SPIRV_HEADERS | — | [SPIRV-Headers-1.4.341.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/SPIRV-Headers-1.4.341.tar.gz) | `https://github.com/KhronosGroup/SPIRV-Headers/archive/refs/tags/vulkan-sdk-1.4.341.0.tar.gz` | MD5 `38bcd69036ec1443ac19b417bef8685e` |
| SPIRV_REFLECT | — | [SPIRV-Reflect-1.4.341.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/SPIRV-Reflect-1.4.341.tar.gz) | `https://github.com/KhronosGroup/SPIRV-Reflect/archive/refs/tags/vulkan-sdk-1.4.341.0.tar.gz` | MD5 `a604577ed56b6687a3bbfa88ab3a6712` |
| SPIRV_TOOLS | — | [SPIR-V-Tools-v2026.1.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/SPIR-V-Tools-v2026.1.tar.gz) | `https://github.com/KhronosGroup/SPIRV-Tools/archive/refs/tags/v2026.1.tar.gz` | SHA256 `35dc16cf2dc64be5b6bbbe86d210e6f4a82b070cffd751605a3365cd8bce2d7e` |
| VULKAN_MEMORY_ALLOCATOR | — | [Vulkan-Memory-Allocator-3.2.1.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/Vulkan-Memory-Allocator-3.2.1.tar.gz) | `https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator/archive/refs/tags/v3.2.1.tar.gz` | MD5 `f32b8374858566854e5f77564ea2e16d` |
| PYBIND11 | — | [pybind-v3.0.1.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/pybind-v3.0.1.tar.gz) | `https://github.com/pybind/pybind11/archive/refs/tags/v3.0.1.tar.gz` | MD5 `81399a5277559163b3ee912b41de1b76` |
| DEFLATE | Yes | [libdeflate-v1.18.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/libdeflate-v1.18.tar.gz) | `https://github.com/ebiggers/libdeflate/archive/refs/tags/v1.18.tar.gz` | MD5 `a29d9dd653cbe03f2d5cd83972063f9e` |
| HIPRT | — | [hiprt-606b4886efabce918dd0634ef71c06615a47c83b.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/hiprt-606b4886efabce918dd0634ef71c06615a47c83b.tar.gz) | `https://github.com/GPUOpen-LibrariesAndSDKs/HIPRT/archive/606b4886efabce918dd0634ef71c06615a47c83b.tar.gz` | MD5 `4bb933c2cf284257625b782d571c02a0` |
| NANOBIND | — | [nanobind-v2.1.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/nanobind-v2.1.0.tar.gz) | `https://github.com/wjakob/nanobind/archive/refs/tags/v2.1.0.tar.gz` | MD5 `363e96957741869bb16ff983c042e72f` |
| MANIFOLD | Yes | [Manifold-v3.5.2.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/Manifold-v3.5.2.tar.gz) | `https://github.com/elalish/manifold/archive/refs/tags/v3.5.2.tar.gz` | MD5 `4fc28c8318bd052f54e66b86b5947601` |
| RUBBERBAND | Yes | [rubberband-4.0.0.tar.bz2](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/rubberband-4.0.0.tar.bz2) | `https://breakfastquay.com/files/releases/rubberband-4.0.0.tar.bz2` | MD5 `93bf3159eb91048e76eba35cf1bf766f` |
| OPENJPH | Yes | [openjph-v0.25.2.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/openjph-v0.25.2.tar.gz) | `https://github.com/aous72/OpenJPH/archive/refs/tags/0.25.2.tar.gz` | SHA256 `ae5f09562cb811cb2fb881c5eb74583e18db941848cfa3c35787e2580f3defc6` |
| THORVG | — | [thorvg-v1.0.3.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/thorvg-v1.0.3.tar.gz) | `https://github.com/thorvg/thorvg/releases/download/v1.0.3/thorvg-1.0.3.tar.xz` | MD5 `6cc2f5ce0225a71265a86f0b88a52c75` |
| LIBHEIF | — | [libheif-1.20.2.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/libheif-1.20.2.tar.gz) | `https://github.com/strukturag/libheif/releases/download/v1.20.2/libheif-1.20.2.tar.gz` | SHA256 `68ac9084243004e0ef3633f184eeae85d615fe7e4444373a0a21cebccae9d12a` |
| ABSEIL | Yes | [abseil-cpp-20250814.1.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/abseil-cpp-20250814.1.tar.gz) | `https://github.com/abseil/abseil-cpp/releases/download/20250814.1/abseil-cpp-20250814.1.tar.gz` | SHA256 `1692f77d1739bacf3f94337188b78583cf09bab7e420d2dc6c5605a4f86785a1` |
| EIGEN | Yes | [eigen-8a1083e9bf41b91fdea6546681f806154efdc25a.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/eigen-8a1083e9bf41b91fdea6546681f806154efdc25a.tar.gz) | `https://gitlab.com/libeigen/eigen/-/archive/8a1083e9bf41b91fdea6546681f806154efdc25a/eigen-8a1083e9bf41b91fdea6546681f806154efdc25a.tar.gz` | SHA256 `cc28a84fdec496c6777596350ea805519bf10f717d21044ae6ba3dd562183a26` |
| CERES | Yes | [ceres-0c70ed3a1a2d6ba47c06c7e8b3b040880bc474db.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/ceres-0c70ed3a1a2d6ba47c06c7e8b3b040880bc474db.tar.gz) | `https://github.com/ceres-solver/ceres-solver/archive/0c70ed3a1a2d6ba47c06c7e8b3b040880bc474db.tar.gz` | SHA256 `bf0bcc78fae884e59dd893693e52510da7cc6866a7444fdae9ba8f19eae266cd` |
| DRACO | Yes | [draco-v1.5.7.zip](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/draco-v1.5.7.zip) | `https://github.com/google/draco/archive/refs/tags/1.5.7.zip` | SHA256 `27b72ba2d5ff3d0a9814ad40d4cb88f8dc89a35491c0866d952473f8f9416b77` |
| MESHOPTIMIZER | Yes | [meshoptimizer-v1.1.zip](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/meshoptimizer-v1.1.zip) | `https://github.com/zeux/meshoptimizer/archive/refs/tags/v1.1.zip` | SHA256 `6aecc2d3b4328f1f5f4127fb16a144de80cc9eb35c32387807c8c04b0b6dbbf3` |
| TRACY | — | [tracy-a64b9a20294d59421a2f57aeca3c6383d8c48169.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/tracy-a64b9a20294d59421a2f57aeca3c6383d8c48169.tar.gz) | `https://github.com/wolfpld/tracy/archive/a64b9a20294d59421a2f57aeca3c6383d8c48169.tar.gz` | MD5 `d316eea1b4bdc265725661c9d5ff67da` |
| JOLT | — | [jolt-5.6.0.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/jolt-5.6.0.tar.gz) | `https://github.com/jrouwe/JoltPhysics/archive/refs/tags/v5.6.0.tar.gz` | SHA256 `6e069ee0172478cc78182047aac87e5310ba14a67a53348ae14cc37801fd3f8e` |
| RAPIDJSON | Yes | [rapidjson-24b5e7a8b27f42fa16b96fc70aade9106cf7102f.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/rapidjson-24b5e7a8b27f42fa16b96fc70aade9106cf7102f.tar.gz) | `https://github.com/Tencent/rapidjson/archive/24b5e7a8b27f42fa16b96fc70aade9106cf7102f.tar.gz` | SHA256 `2d2601a82d2d3b7e143a3c8d43ef616671391034bc46891a9816b79cf2d3e7a8` |
| OPENTIMELINEIO | Yes | [OpenTimelineIO-31e3101e750be2aa992274ac02c0679077872e57.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/OpenTimelineIO-31e3101e750be2aa992274ac02c0679077872e57.tar.gz) | `https://github.com/AcademySoftwareFoundation/OpenTimelineIO/archive/31e3101e750be2aa992274ac02c0679077872e57.tar.gz` | SHA256 `e24df04cc0b4bc266d3859c212f7d97e5198f99d49ea889d57f8fb21d8e350e1` |
| KTX | Yes | [ktx-4.4.2.tar.gz](https://projects.blender.org/blender/lib-source/media/branch/blender-v5.3-release/ktx-4.4.2.tar.gz) | `https://github.com/KhronosGroup/KTX-Software/archive/refs/tags/v4.4.2.tar.gz` | SHA256 `9412cb45045a503005acd47d98f9e8b47154634a50b4df21e17a1dfa8971d323` |

<details>
<summary>Preview LFS payloads in the checked-out source</summary>

219 paths refer to 208 distinct Git LFS objects. For each row the pointer supplies the expected SHA-256. The LFS batch endpoint listed above returns the download URL for that OID at request time. The host library submodule is unpopulated in this copy, so its individual paths and transfer URLs are unavailable here.

| Path(s) | Bytes | Pinned SHA-256 OID |
|---|---:|---|
| `assets/brushes/essentials_brushes-curve_sculpt.blend` | 821857 | `4ede28320eb8430c06899f4937be5b1b980b06688189e03ad0b1ee56f1e1bd1f` |
| `assets/brushes/essentials_brushes-gp_draw.blend` | 497193 | `0596dce9286b824c31af67197b96e83a0c4a42ce2dbb36f40dfc8ecab3fe9f06` |
| `assets/brushes/essentials_brushes-gp_sculpt.blend` | 357873 | `235631a858c91b5cdaf70240ce0ed15bff11ef4474767e983d169a1bbf4723f6` |
| `assets/brushes/essentials_brushes-gp_vertex.blend` | 245965 | `ee1e9eee2cb898c3e95dbe2c059a51d4a5ec863a0d9bbd8ea1beb7d6a20bed06` |
| `assets/brushes/essentials_brushes-gp_weight.blend` | 196914 | `ec19a0cbca6a8413c45a25994a3db0ce1c7c8bd002d1968069dc1b558ce8500e` |
| `assets/brushes/essentials_brushes-mesh_sculpt.blend` | 2715184 | `f8b15126658f5a4ac455b0826a7eeae026576ed7c2ac45562d8880383fbf03bf` |
| `assets/brushes/essentials_brushes-mesh_texture.blend` | 972168 | `6c57caeaaa1f16e175783a2fbcbabf8772e108414edca92cad52bcc8019110f8` |
| `assets/brushes/essentials_brushes-mesh_vertex.blend` | 600678 | `7b4b5d973f1bc4a06f7553afc96c7cb0bd9a0c17921cd65903b40395eccd3300` |
| `assets/brushes/essentials_brushes-mesh_weight.blend` | 405717 | `ec029f2bb0b1be0c7ee3acb913bcf4c17e7217c4f5c8d97a5c6f577abf71d856` |
| `assets/nodes/compositing_nodes_essentials.blend` | 1387150 | `3307ae8ac73d52fdf15b029aea5365086bb30264eb7a8b3508c4d0355cb79f13` |
| `assets/nodes/geometry_nodes_dynamics_assets.blend` | 307332 | `a2e6b4013abfc3b9355927e33b2ae5af2182dc079e820041124652a75ce7b100` |
| `assets/nodes/geometry_nodes_essentials.blend` | 705336 | `4271f315f5703d26ab412888a4212303ce3fb667b87c48538c1c0960e391611c` |
| `assets/nodes/principal_components.blend` | 84028 | `91cb8cada033daab6c6fbb8aef4767782cf75be867a0c2f38ced742160f38a39` |
| `assets/nodes/procedural_hair_node_assets.blend` | 2488249 | `60112b3022238b9a6571ef6e117a677d9c722f90b26e32fe02742f3c0328e2c4` |
| `assets/nodes/shading_nodes_essentials.blend` | 84063 | `ffdaf64a4777233f6e47799bad17825a6c1e07c500eb1d9d0c23997f745327ee` |
| `release/datafiles/DejaVuSans-Lite.sfd.bz2` | 182524 | `7efca456dfd439a2218082d4293bd109892ba53c064064dc4d019bdb024f6422` |
| `release/datafiles/colormanagement/icc/g24_rec2020_display.icc` | 464 | `b03c9218e82ab12fc4fcac7f5a0fb10ff53ebc7ad8387ae68a6d8cf5d4dfbaa3` |
| `release/datafiles/colormanagement/icc/g24_rec709_display.icc` | 596 | `4d10744483b3448daceacc880566b004cd90aa0ca535f651c8c88ba61646c965` |
| `release/datafiles/colormanagement/icc/g26_xyzd65_display.icc` | 464 | `58ac463ea778e9b70692971dd4ba9071363a03aba77043894162b1ad6c051da7` |
| `release/datafiles/colormanagement/icc/srgb_p3d65_display.icc` | 480 | `cb51de38e482ee974c0c76b9689e16aad04bad16e226fed2f30c842d15ff3a3d` |
| `release/datafiles/colormanagement/icc/srgb_rec709_display.icc` | 480 | `c56e1685d888f5edb92fe07f2750f387f8fe8e91b32ff8fb0b56bfbbb9458353` |
| `release/datafiles/icons/brush.draw.dat` | 1952 | `f16b79b0e9bff04a23e7e8b634de603b7ef66670c6ddee1616542c82bd90bb53` |
| `release/datafiles/icons/brush.generic.dat` | 1574 | `4b5f9d158a881606f64064b0bf7776fb5cbe3a6f0b30800631ea5c6244d9197e` |
| `release/datafiles/icons/brush.gpencil_draw.erase.dat` | 1052 | `33423bd93aa73e02d6cfd0fee443fe6d5a105b4c730b7ddf011c59f32dacde90` |
| `release/datafiles/icons/brush.gpencil_draw.fill.dat`, `release/datafiles/icons/brush.paint_texture.fill.dat`, `release/datafiles/icons/ops.paint.weight_fill.dat` | 2276 | `55d9b56988868c4b42a1cfaf2884d0c7455131dda5d9c40b6f3473ae686b1a6c` |
| `release/datafiles/icons/brush.paint_texture.clone.dat` | 764 | `bd69d5008200039b7030d4dd13e71cd76c1a716fc96fd71fc34b1d4722f1a56c` |
| `release/datafiles/icons/brush.paint_texture.mask.dat` | 476 | `bbb4980d5bd6af99bcf5e558c919a2eca23d63dcc366f542bb8911e688ff379b` |
| `release/datafiles/icons/brush.paint_texture.smear.dat`, `release/datafiles/icons/brush.paint_vertex.smear.dat` | 1700 | `e5a560ed1f5ba78fa8909efec0f2f3aed4033e81e3d9472fcaa41fef63a00f3b` |
| `release/datafiles/icons/brush.paint_texture.soften.dat`, `release/datafiles/icons/brush.paint_vertex.blur.dat`, `release/datafiles/icons/brush.paint_weight.blur.dat`, `release/datafiles/icons/ops.gpencil.sculpt_blur.dat` | 1304 | `a06f9541ef8f0f4e4eb1e06999cf26be3721a9edf4a6e9f8c19c70db85cfc127` |
| `release/datafiles/icons/brush.paint_vertex.average.dat`, `release/datafiles/icons/brush.paint_weight.average.dat`, `release/datafiles/icons/ops.gpencil.sculpt_average.dat` | 3284 | `d4b2f6c792b12926cf03cddd9b9b6d2166c7e37fed22d48ce7503ef3a1f75e7e` |
| `release/datafiles/icons/brush.paint_vertex.replace.dat` | 2942 | `386ca440fbf2f4bb7d39b33fa543bb291a0c2f8a4c40b79ac4e64172235b77e2` |
| `release/datafiles/icons/brush.paint_weight.smear.dat`, `release/datafiles/icons/ops.gpencil.sculpt_smear.dat` | 1700 | `62d81b0f5c74b07654fbd74adcee09e40bdb536ec7889a37c37e954565a67a17` |
| `release/datafiles/icons/brush.particle.add.dat`, `release/datafiles/icons/ops.curves.sculpt_add.dat` | 2132 | `1d64974550ba2c64dabcd446803307b658aac78b3a73ec284a90f91822eb3383` |
| `release/datafiles/icons/brush.particle.comb.dat` | 4472 | `c4b91ab4190297a377ac73d9c79c0d2359d1753eec85cfd873470c23d41fd900` |
| `release/datafiles/icons/brush.particle.cut.dat` | 2456 | `693099c7084aaaed1c6e069097267c0294a8a845eba54e80209c1f6edda383e4` |
| `release/datafiles/icons/brush.particle.length.dat` | 1736 | `bf1c34055267f658b4443ecedc6f8a1ef113fc001267a0dd2af7a57e3bff1227` |
| `release/datafiles/icons/brush.particle.puff.dat` | 1718 | `6f3d23abf20de6d3fbd86dba62f5a485230ba88551ee9768e8df0c1c5554ee3e` |
| `release/datafiles/icons/brush.particle.smooth.dat` | 746 | `b06e366c76f1c218cb219d1a995ced1617ce1579d9c55136b0b4f49d69c24a97` |
| `release/datafiles/icons/brush.particle.weight.dat` | 2924 | `fe4b22e81e2d7439c7131de00c6df9b0710741ab072f9ede4f3f8b96a86015ba` |
| `release/datafiles/icons/brush.sculpt.dat` | 1934 | `03c491ce6e2aa1b22af8a78ac82db45e01d081bb15a6ddcdd2addb807d0a4dbc` |
| `release/datafiles/icons/brush.sculpt.displacement_eraser.dat` | 3104 | `89449222a8e763697b33dbc0479e392a6580be4086465f8f79ab9f05dcb2a7b3` |
| `release/datafiles/icons/brush.sculpt.displacement_smear.dat` | 3968 | `9151471ac435103e4c936e6e72634d6bde97aed0d5979ca76b419324eb455dd9` |
| `release/datafiles/icons/brush.sculpt.draw_face_sets.dat` | 3266 | `8c5cf9b3dff149cecb682d39849e9c758de6726deca850858600f111bf2767b7` |
| `release/datafiles/icons/brush.sculpt.mask.dat` | 3266 | `0476def2be9046e2cc7cf5beb1966c5c325a24c35b08be0f41e201c697856858` |
| `release/datafiles/icons/brush.sculpt.paint.dat` | 1574 | `12ef3053acfd5a97d553a9e002adfa779fdf91c7f437afea1f504e11ef5b1953` |
| `release/datafiles/icons/brush.sculpt.simplify.dat` | 5480 | `a19c16225085ac1fcb8da5a2994499e3e573a1fd8b1adbecc02be103ce3bbe15` |
| `release/datafiles/icons/brush.uv_sculpt.grab.dat` | 3176 | `4fe94dc2b1418ab7c52f859724bc85cf4aa566a5b6e8702fe51549a26f07329f` |
| `release/datafiles/icons/brush.uv_sculpt.pinch.dat` | 3968 | `471656f05b501ba784ff69ab3b9c3240a1f37b316c154dc118887a149b37c78d` |
| `release/datafiles/icons/brush.uv_sculpt.relax.dat` | 7208 | `7f80bdf27d5fe8d5225031e2a72ef35388709ce132379b7a81da6de422c99510` |
| `release/datafiles/icons/none.dat` | 3014 | `5632ac4cb9c572b4403162ceb15d4dc2d601e4f9e4b63a3c0cc34f062e3abf2a` |
| `release/datafiles/icons/ops.armature.bone.roll.dat` | 1646 | `e5af15135066f995859038ddc0c16843d7aab525bed2eb3ad90595180fd6d6c9` |
| `release/datafiles/icons/ops.armature.extrude.cursor.dat` | 1502 | `18491cf431f2e6c39e751564e5a86acbe694a023f6e390b50c5cb77da448aa1a` |
| `release/datafiles/icons/ops.armature.extrude.dat` | 1250 | `b343696858d818a9a25262bebf552b16614c630a16b27e3b69e8f4c47211fb85` |
| `release/datafiles/icons/ops.armature.extrude_cursor.dat` | 1574 | `0c5c53e9972ce4c1bff0f14601a8905dea3a962fa2e7b3ae2f5bc3cb10a50ea8` |
| `release/datafiles/icons/ops.armature.extrude_move.dat` | 1376 | `8417a96ae76089c2abef139935f6174c498867d53c3247a72b48c6ba7a49853d` |
| `release/datafiles/icons/ops.curve.draw.dat` | 2402 | `eb8572b4837645a62f714e13b12d80351a5418c9b729089b4f2dc297b1106d4d` |
| `release/datafiles/icons/ops.curve.dupli_extrude_cursor.dat` | 4202 | `1acac49448d27d3bcadc996eacb62c9452a83a349e08899660bf52a36259a82a` |
| `release/datafiles/icons/ops.curve.extrude_cursor.dat` | 1844 | `2d03e0cd2eb28f8f47466b16273f234cd2549d52e20b241893e68e3289ac09f7` |
| `release/datafiles/icons/ops.curve.extrude_move.dat` | 1754 | `f7e23ffe7c5b872b558b3e31973ddfacaa1c97fbc723cf8943f875bd7b79db4c` |
| `release/datafiles/icons/ops.curve.pen.dat` | 3374 | `c4d097357a95179ca7562afb99f755aee73159faadfb8d28ce69b99dcd844018` |
| `release/datafiles/icons/ops.curve.radius.dat`, `release/datafiles/icons/ops.gpencil.radius.dat` | 1466 | `4de5fba0f1c0860a1ee0a004e750555e189dc3a4f45767b9a6582274135fe6a8` |
| `release/datafiles/icons/ops.curve.vertex_random.dat` | 1412 | `083e37ee8ae80ba9f35108d3d28be54d4d6362408da97e0c30c36658a85fd8b7` |
| `release/datafiles/icons/ops.curves.sculpt_delete.dat` | 2060 | `2a87dc4a0f2bbbb1f9f8062cf71a1bdad02568bbd6772c125dd7201c9b0bd1c2` |
| `release/datafiles/icons/ops.curves.sculpt_density.dat` | 3032 | `cdf5c0b9a80a9ba692855b2f5bee4472290abef2357633cb27687cc237f5926c` |
| `release/datafiles/icons/ops.generic.cursor.dat` | 2168 | `eb295216341138029716c499b35005379b4e9297a1a7f35b5d13a852bd031111` |
| `release/datafiles/icons/ops.generic.select.dat` | 296 | `3f09dda7752731609385ee216288cc0ed416a0ee174efa34117130dd53fd7900` |
| `release/datafiles/icons/ops.generic.select_box.dat` | 2312 | `7da57dfd654cc9bb102ab1a737a49bf345252264fe4c14dcc01b27a847478699` |
| `release/datafiles/icons/ops.generic.select_circle.dat` | 2564 | `d9fcd517fdc3ac01765901f870679f446953ba55ee62c3ce1b2b7541217a0cea` |
| `release/datafiles/icons/ops.generic.select_lasso.dat` | 2402 | `25bcdb44f86822eaa63ece6d99318b38c1df4b9cb81be966e0c253e941496c6a` |
| `release/datafiles/icons/ops.generic.select_paint.dat` | 1790 | `127196c1adc3b5140cd6caca2b21f77c37ce75c89495f56f3b223c54b3fd76ea` |
| `release/datafiles/icons/ops.gpencil.carver.dat` | 3986 | `b8ded96a8b53a9df98193a8a9e332dbb4fbd1d8590599c9db7159a439894232a` |
| `release/datafiles/icons/ops.gpencil.draw.dat` | 1538 | `5dd6e4bd02dc779204b2e71d305c331b93ff074f49c400a1067c6a2a04f0b66f` |
| `release/datafiles/icons/ops.gpencil.draw.eraser.dat` | 1412 | `c7a7ad328b9a7d4010af05d0e8c7a74423fe92861dfcb8e40b751fdbb1ecb948` |
| `release/datafiles/icons/ops.gpencil.draw.line.dat` | 728 | `34e81d183975e6912c450e1049d6162105dd2040b217e3d2c9ebb5485b9cb6f0` |
| `release/datafiles/icons/ops.gpencil.draw.poly.dat` | 854 | `c9a1d8ebbff4fba4c8f1fc7f97faf350d804bf78e6370bf8a52fd9183aeb2715` |
| `release/datafiles/icons/ops.gpencil.edit_bend.dat` | 1664 | `9e1c260fde74e56a5016135a86ac24496aa72fd53cc3fe8d01a79a4555acc0db` |
| `release/datafiles/icons/ops.gpencil.edit_mirror.dat` | 3230 | `a12f0aacf4088e0bbc4411cca9d44b58decba8ad4da9952bb022c755840632d2` |
| `release/datafiles/icons/ops.gpencil.edit_shear.dat` | 1286 | `1ca17a6ce5ba416875f5fde2c26b1c55951141a80503008081d4f650311dd841` |
| `release/datafiles/icons/ops.gpencil.edit_to_sphere.dat` | 152 | `c6e239cfb6ddfb1ec8a3dfc0fa69cf73680f1831bfe2dc870bacc2a184de853d` |
| `release/datafiles/icons/ops.gpencil.extrude_move.dat` | 5426 | `d492288780d646277d2774674dc2bfa1e24221b6937fddd1869fba7bb41ee4f9` |
| `release/datafiles/icons/ops.gpencil.primitive_arc.dat` | 1142 | `2f06e4b63fd0ce9b27ce96482f84440d5c6ce587911296a1c9f4b72260d8a9be` |
| `release/datafiles/icons/ops.gpencil.primitive_box.dat` | 332 | `11487a34115e894cc370f0f932d8dbab7d72ddd66d3404a9df0c79cc153f3cfa` |
| `release/datafiles/icons/ops.gpencil.primitive_circle.dat` | 1340 | `22a9bcf107bc051100c8e635d4380c90024a166779f21845eaf858caa114e5e7` |
| `release/datafiles/icons/ops.gpencil.primitive_curve.dat` | 1196 | `0ce05f984c1d7b92356ab889fde3bc868fbb1018e37ab60c6d03b97397d32404` |
| `release/datafiles/icons/ops.gpencil.primitive_line.dat` | 440 | `0e73a9a204c1d9e2727d1b3d6ee796bf5199a6de4def80f644b782460e15d462` |
| `release/datafiles/icons/ops.gpencil.primitive_polyline.dat` | 674 | `d071717a9bfe74e3737979ac8619f051d1658a56b8b9d28e1a2d1dc9500e08ef` |
| `release/datafiles/icons/ops.gpencil.sculpt_clone.dat` | 3176 | `965fe7283e234a4baa6f9a5aa4d18e1e82a0f45e7311411eb7f1fb4e26fc4dcb` |
| `release/datafiles/icons/ops.gpencil.stroke_trim.dat` | 1214 | `e5a54e50e241616b3494e10615f139e8cc49e25795ecb2f536347f3c322b02a6` |
| `release/datafiles/icons/ops.gpencil.transform_fill.dat` | 2132 | `0e058974b029d99484341f82253fdc4e68b3fc4a001e092b749478dbca52f349` |
| `release/datafiles/icons/ops.mesh.bevel.dat` | 422 | `740070114a6f55ac9ac99f9d22fd7012ae785006e1a44e33bfc64c74cde040a7` |
| `release/datafiles/icons/ops.mesh.bisect.dat` | 494 | `4ce939fa079cae558980ed3338e4a4577ee7fa6f26d6ee9b1ee21bae2d749320` |
| `release/datafiles/icons/ops.mesh.dupli_extrude_cursor.dat` | 746 | `9e89a90f1b287b5431c5e9fc2d9705e4db0d2badfa9545646ba68124dc861646` |
| `release/datafiles/icons/ops.mesh.extrude_faces_move.dat` | 296 | `62eae3218ba0524bd143422afb59f9494b917378209c9924437747387c796cf8` |
| `release/datafiles/icons/ops.mesh.extrude_manifold.dat` | 494 | `453bad97a0db3fc7ac87d54d11044d9f1a38919dfda586a833c203c3c85a7c54` |
| `release/datafiles/icons/ops.mesh.extrude_region_move.dat` | 350 | `962b086de9b0eb9750c78caa9a208802f5b1000b55fd136eee38241acd25919d` |
| `release/datafiles/icons/ops.mesh.extrude_region_shrink_fatten.dat` | 224 | `c498c6de6c684956a40b3ee7520552c1808fce02b8779e88b80d9bac25fb39da` |
| `release/datafiles/icons/ops.mesh.inset.dat` | 584 | `60f6a55f7ca242ac3d39db4f300521003f00e837c11d7d469553e00aef289a6c` |
| `release/datafiles/icons/ops.mesh.knife_tool.dat` | 1520 | `8fec9a897bb43f07ec691f0aaffcc9943884250cf2d98f44db68872fc9e95e20` |
| `release/datafiles/icons/ops.mesh.loopcut_slide.dat` | 710 | `63a593ec0aaf5df19df1dfa0d219fd7b568bd989320840fc913d70d3a6f4e002` |
| `release/datafiles/icons/ops.mesh.offset_edge_loops_slide.dat` | 962 | `d73a3c6f1223399ff68be37afb64f302b287409e7aa64afb4e26653d4aa97d50` |
| `release/datafiles/icons/ops.mesh.polybuild_hover.dat` | 4598 | `0dc1239bcd378b710e67e63241d9c0e3066d7e01c1031f9a248232543681ccce` |
| `release/datafiles/icons/ops.mesh.primitive_cone_add_gizmo.dat` | 2132 | `e9bc33ceeb716a28e88f9a8b18352f609f60d7c697b26671498f633af48ea78e` |
| `release/datafiles/icons/ops.mesh.primitive_cube_add_gizmo.dat` | 980 | `863b6fe4f5b0c41f5c9a1a8e37bd49e1ebb06026ac56a4bb0d79bcd288425d4a` |
| `release/datafiles/icons/ops.mesh.primitive_cylinder_add_gizmo.dat` | 5372 | `427cadfbf933eec90c1ef67e2d9b3a2f8438a7a899a331c745787b8151cd5abd` |
| `release/datafiles/icons/ops.mesh.primitive_grid_add_gizmo.dat` | 566 | `b253b1179f0ac9923ee4dfc44b5defaaa1d78d940cac96438ec40d600343f8ff` |
| `release/datafiles/icons/ops.mesh.primitive_sphere_add_gizmo.dat` | 6236 | `0914ddefbda5b12bfcaa2285f5b4a5ac9d4b21d7c1041a8d8cfa29b5de55e8f0` |
| `release/datafiles/icons/ops.mesh.primitive_torus_add_gizmo.dat` | 8252 | `83e183f21e2714f71eb5678c4f364ccb678f0e202beaebd915bbdc5a3404a0dd` |
| `release/datafiles/icons/ops.mesh.rip.dat` | 944 | `f5419a017c0b1680508cee88f5cb75f81d40f2bd0baf0719a92cc2746d41feeb` |
| `release/datafiles/icons/ops.mesh.rip_edge.dat` | 890 | `f8823c5e4f9de2199a08fe63fd45efc66078a6aff4bcb5cb4f7332e3f6606435` |
| `release/datafiles/icons/ops.mesh.spin.dat` | 1538 | `681f49a553863ac96a3876c6e15b8ae33ad702d3847ca80147ec9d56f1379fbe` |
| `release/datafiles/icons/ops.mesh.vertices_smooth.dat` | 296 | `9cbd0e1dae1c053fe0f09ba527c5b4a5eb7d9041a446390de146ca1f78ac4c0c` |
| `release/datafiles/icons/ops.node.add_reroute.dat` | 3050 | `f3c642e2fe94aea781d13e7132917ffa00bbdb4dd5fb305b6278fcc98bf3dead` |
| `release/datafiles/icons/ops.node.links_cut.dat` | 1628 | `22d6fabf47a38045be87f5df104c3f791562bbb94af41820d0621d8cc5910647` |
| `release/datafiles/icons/ops.node.links_mute.dat` | 2078 | `a9e18582116dcae54b54ee96ea94325e2dafc753a30539d35964ce63b1281b7b` |
| `release/datafiles/icons/ops.paint.eyedropper_add.dat` | 962 | `30b87385452a3b06fa70970180f788182ee3397b9f098b7869c9886af0351c01` |
| `release/datafiles/icons/ops.paint.vertex_color_fill.dat` | 1844 | `90d1b7134b2226b8daada0bb14f98cec505c3d586b0278e6637bcfee1992f881` |
| `release/datafiles/icons/ops.paint.weight_gradient.dat` | 1232 | `a074c36806c99a2cfcee781c9c3d1be1393e20a1cc87de71e96f8fc9f862ed07` |
| `release/datafiles/icons/ops.paint.weight_sample.dat` | 1502 | `1460a1e0da4f17a168012940464b707c7cbe074d7a47fa2c7f6fe1d20ca19d12` |
| `release/datafiles/icons/ops.paint.weight_sample_group.dat` | 1538 | `636424b98543a8abc8de3b625b0a864d75cd82bad9301220df22206136400cc7` |
| `release/datafiles/icons/ops.pose.breakdowner.dat` | 1682 | `72332769d6e1060cb6f068d18d1cbdb0d1b8977073f8a1b6011f2678557ef96b` |
| `release/datafiles/icons/ops.pose.push.dat` | 2384 | `12c0dff9843824aa3e82d68cebe67f7fcdc4ddb40b80f7cafcf978b2bbcaa555` |
| `release/datafiles/icons/ops.pose.relax.dat` | 1394 | `4d27a1e765bd231ec01899c6df11f60608b3a23566e3a0d4de3ca87af18d3859` |
| `release/datafiles/icons/ops.sculpt.border_face_set.dat` | 1142 | `2d89df3c3e696da0da3fdbee89e65d808a6340b955e89ebf6e43ab5312a0c7c5` |
| `release/datafiles/icons/ops.sculpt.border_hide.dat` | 620 | `955dc13406c6dc5b6c30c8370188f369f74926a599a417a1d13b9f7964e546fb` |
| `release/datafiles/icons/ops.sculpt.border_mask.dat` | 944 | `f1d61be13918e222f2c41e74bffee0dcb196ae0ed25eb2481e0d8beaa273e4d8` |
| `release/datafiles/icons/ops.sculpt.box_trim.dat` | 1736 | `70eea74ecff30c781b797aba494c12d5e2bd62326998bc1ffb78327723005d6f` |
| `release/datafiles/icons/ops.sculpt.cloth_filter.dat` | 5570 | `7d09dd54067918e1acd3a530309b02e4d7a081da3c56ba8af1431205ce9c0193` |
| `release/datafiles/icons/ops.sculpt.color_filter.dat` | 1700 | `0f367f0e7dfe7c8545e0beb432a18c10ebad8f42fe83851f5e1e11626417f6d8` |
| `release/datafiles/icons/ops.sculpt.face_set_edit.dat` | 1700 | `065961069698bc5d07f10852e9c18a2c35823c93f457f82135f7df2ea61716aa` |
| `release/datafiles/icons/ops.sculpt.lasso_face_set.dat` | 3284 | `fa225076aba95166e89eb2c6b2d875a5726bec0d7333c73c9e9f567bb2b7c9ba` |
| `release/datafiles/icons/ops.sculpt.lasso_hide.dat` | 2240 | `15cd7f2f4e89ed392bc7d3b9175c4429067f87f8064b8312db679b360c176b65` |
| `release/datafiles/icons/ops.sculpt.lasso_mask.dat` | 2978 | `446b2365d244dc61fce95d6dd2aaacf98971f5978d3c40a6f932ddb1c648ed70` |
| `release/datafiles/icons/ops.sculpt.lasso_trim.dat` | 2816 | `e499d12ec53d16a2eb7b7496bca522c954f92f9983831777da8676305171ccdc` |
| `release/datafiles/icons/ops.sculpt.line_face_set.dat` | 1790 | `40fda788211766626759199dadcd57ad82c9f491cdc8e3a6db55a94702d01353` |
| `release/datafiles/icons/ops.sculpt.line_hide.dat` | 1034 | `fd46634964fdd1b9d604b77d860cbf935d8c1666827397e05d82fcd9ef6b1bbb` |
| `release/datafiles/icons/ops.sculpt.line_mask.dat` | 1412 | `66c008cd73458cfcad9bb22902de1cbc155512eecdf243aa6c58a22484826163` |
| `release/datafiles/icons/ops.sculpt.line_project.dat` | 1016 | `58ae0011d9c4a03100e8f5573169c67213d7d0583234c9d9d16238ffdec91832` |
| `release/datafiles/icons/ops.sculpt.line_trim.dat` | 1826 | `6604dd2bb6d193f4c9259a905b112578e32e9786ae57089bc1aa8bf3c7e78b5e` |
| `release/datafiles/icons/ops.sculpt.mask_by_color.dat` | 3716 | `1b8c0946caf311192c37276f20d17215c9940aa83d3cd3519c124aeab4dd998d` |
| `release/datafiles/icons/ops.sculpt.mesh_filter.dat` | 2060 | `7a7cdaa99b48ca8556bb16d7511f627d06ca6f36cb4462ec36405fd67f26a4fa` |
| `release/datafiles/icons/ops.sculpt.polyline_face_set.dat` | 4436 | `14c210a4c15342ba2ef8e4da8200f957a7a8c290d7b5d06180c15cc2d6e3e479` |
| `release/datafiles/icons/ops.sculpt.polyline_hide.dat` | 3626 | `3a6f7de7ab4a4a21e4faa63988d9c070c1de6028b52dc917f21344177fa408a2` |
| `release/datafiles/icons/ops.sculpt.polyline_mask.dat` | 4400 | `4af58556ee21b6819ba69187dbb5e54b84d630f3fce2f1410f15dfaa8c002b48` |
| `release/datafiles/icons/ops.sculpt.polyline_trim.dat` | 3716 | `d2cbf25ed93ca242769a82e2414e406b963017b6d97aa705552785b1ce3b8f7f` |
| `release/datafiles/icons/ops.sequencer.blade.dat` | 1376 | `0bb3199539b0e7d0e41d44efeb56e9c2a515fb644ad8b73a2d02ebb592ad4b79` |
| `release/datafiles/icons/ops.sequencer.retime.dat` | 3950 | `ee2de3eb373bc4bbcf8d8aa6ae192c08d6a09c67bdaf4d9f4e5dda7613b365a2` |
| `release/datafiles/icons/ops.sequencer.slip.dat` | 3050 | `c729938f088f015b66fae7dfde3e0a2f18dee4c790b74354e1f4e372bdc03441` |
| `release/datafiles/icons/ops.transform.bone_envelope.dat` | 1736 | `f0f5e10b2e76f1fbddd299c192f7ce7707b6bbded552b3979d1735b90d75bd71` |
| `release/datafiles/icons/ops.transform.bone_size.dat` | 1052 | `5c073cd4091e313c9bf5b27d0ea36f59de262707b890dc34de72ae7c34fb45e2` |
| `release/datafiles/icons/ops.transform.edge_slide.dat` | 800 | `607cc2140e83179f4afa53ffcd37005926091d0b6db77237719a81d65e2ee6e4` |
| `release/datafiles/icons/ops.transform.push_pull.dat` | 728 | `a0e107b39c8962389dbe84991393c91f9d9937bb7952ca2b49343686996a6486` |
| `release/datafiles/icons/ops.transform.resize.cage.dat` | 2456 | `02de52ec4a5b3178c7306d1127f774310a18fc30a35eecaa88a01836c3a512dd` |
| `release/datafiles/icons/ops.transform.resize.dat` | 278 | `c0b3db9821368c5177c0fc7e723001f1dca0568949ec53833451cb41414bebc8` |
| `release/datafiles/icons/ops.transform.rotate.dat` | 1664 | `397b60f9a6921263768b47ab1806d7f1935da2867fc97849e484df797e663aca` |
| `release/datafiles/icons/ops.transform.shear.dat` | 206 | `41c5642ecba5f36ae4c7186984e1c02b6eca6eb6a31e371e52d0685fb00aa21d` |
| `release/datafiles/icons/ops.transform.shrink_fatten.dat` | 1142 | `4cd037ce44b6bacd683bac1ff309f9de5f247924dced9ea166a1ff097ddeec48` |
| `release/datafiles/icons/ops.transform.tilt.dat` | 5822 | `456f7472b40983dbbaec7496a9b9f0479640648876e386fac19c2f97fccd5b6c` |
| `release/datafiles/icons/ops.transform.tosphere.dat` | 1232 | `0cf7f85ac1657862c7b91b6e5da3fd71c4ca85b4c2cf8749692f40aa756ae59a` |
| `release/datafiles/icons/ops.transform.transform.dat` | 1700 | `c45737094488f6ec549587b22b0897549279fd4f0f4ed06be7e4bbe428819f0e` |
| `release/datafiles/icons/ops.transform.translate.dat` | 224 | `fad345643f6c3edc6b6c5dc6b773581376a4238adb3013366056ef06576ee9a6` |
| `release/datafiles/icons/ops.transform.vert_slide.dat` | 1106 | `77847ef7ea89060326c62d032a9e6de1aa0a599621c2e288a3eeff48c02abc87` |
| `release/datafiles/icons/ops.transform.vertex_random.dat` | 296 | `efd93373edf9dee26467c4e7fb292ec0125f01682929e1e8d4521f5902484f1d` |
| `release/datafiles/icons/ops.view3d.ruler.dat` | 1772 | `c3cc4544b73d8546460457fe157cb079a77af16bfbb27f84d2360772fcb99570` |
| `release/datafiles/icons_blend/toolbar.blend` | 2859369 | `17678861c7798ce603f922c09ed564c6c8f0325b97e61b30e2f94ac569411843` |
| `release/datafiles/preview.blend` | 1412458 | `703261170a8bc0d73f7c4a5563c9b3243db2befce8bf1e4a480936baec50b92f` |
| `release/datafiles/preview_grease_pencil.blend` | 1126319 | `de7feab80a8906b22f3d94cb8e6730e1339f0bd725a04d7838f406d3cd348bc3` |
| `release/datafiles/splash.png` | 597574 | `d4dcf853923af5bb4fff2b84d865512ca85bcb6905030fd4bda3793decded6aa` |
| `release/datafiles/startup.blend` | 121384 | `1335899143c7e77bcb0f6e3680fd99078c0af481a1238e4ed7d4eb1ddd7dd353` |
| `release/datafiles/studiolights/matcap/basic_bright.exr` | 54248 | `40086db175648e9256fa9fe75d710b9bdc78b5bd6a78b7e527b1fde54193e1b4` |
| `release/datafiles/studiolights/matcap/basic_dark.exr` | 36896 | `ef4896291fe4d34e3beb1b26f6b1eacee10f996388958092ec88a457ec754618` |
| `release/datafiles/studiolights/matcap/basic_grey.exr` | 47801 | `7266ec195b78964248bbd526c8895036ef7cda0e099b62bac67ab860d1ecf34c` |
| `release/datafiles/studiolights/matcap/basic_side.exr` | 50527 | `4596e70ba9351907a93048c70660fdefca159a91ccdedc01d6fde3753ddf8c1e` |
| `release/datafiles/studiolights/matcap/brush_thumbnail_preview.exr` | 49457 | `f31d8d6282d5d0051bba1683479d54f6b977671665a2f5deb63ce3233f7e19a6` |
| `release/datafiles/studiolights/matcap/ceramic_dark.exr` | 73875 | `e5423d61327ec43d5100c1995c5c6460cd7233376f1c02142366c7191db926ef` |
| `release/datafiles/studiolights/matcap/ceramic_lightbulb.exr` | 74500 | `a67d3d22fd811d09ac4ed1d33a7b1b8e6c982fdbadb405068d33b014ab1891f7` |
| `release/datafiles/studiolights/matcap/check_gradient.exr` | 77595 | `8e783b6d6e7f277563b54add1083f58bfff0de6722f38cb32464e15feade3b6a` |
| `release/datafiles/studiolights/matcap/check_normal+y.exr` | 87477 | `9242d1eb83b9c27ce8ee9f2ddcb06e74d94ab7ddccdd578d4e7f8c170e4048c6` |
| `release/datafiles/studiolights/matcap/check_reflection_horizontal.exr` | 287341 | `f7f15db965868fb1fa79f1b78996b6ec8dd0f17009383c873833a02f0eca6f05` |
| `release/datafiles/studiolights/matcap/check_reflection_vertical.exr` | 172531 | `942f1368655800fb16a99ca423d4af5e6476b2f577f53bf2486719a008413baf` |
| `release/datafiles/studiolights/matcap/check_rim_dark.exr` | 54070 | `f2d423aa4f46c903ab70982343ec0298e6c7683980c002ad843d00847d49d1ec` |
| `release/datafiles/studiolights/matcap/check_rim_light.exr` | 65682 | `eeba5fa1e80a735efe90defd9ca6f2a22af7ff302810a44756a7b337a01543e5` |
| `release/datafiles/studiolights/matcap/clay_brown.exr` | 57812 | `ab2f06971cca555e8d3d86ee6fa9ddceeab21b8dd7b50423c521f6c87bf671c2` |
| `release/datafiles/studiolights/matcap/clay_green.exr` | 50917 | `f35b3b175f5526fbece6aa16ee7278f787b6eef86b79e4deb45ca67e0f0f97a6` |
| `release/datafiles/studiolights/matcap/clay_studio.exr` | 63791 | `099947ff59d80135268f42f8f19058093fc734ae1a5c95e2c27691f82294a382` |
| `release/datafiles/studiolights/matcap/clay_warm.exr` | 58983 | `a91122d8e2aa0bdc17165e4a72ccaca991d5554d3a8afebce6e3fc35881df159` |
| `release/datafiles/studiolights/matcap/fullmetal.exr` | 121208 | `8bc9f3974c3003d02f24b91d3f0cbbd8a1c40faca7ec3d0f0e4164704004807c` |
| `release/datafiles/studiolights/matcap/hard_surface_grey.exr` | 58884 | `efc053eda7ad67b8ff1046efbd97939e794c18f3c228dd98dc22f2064b4dfbcc` |
| `release/datafiles/studiolights/matcap/hard_surface_red.exr` | 102872 | `0e480f93f18e88603b555a8a8b16a7149178ed1cb842e5513a77636397183366` |
| `release/datafiles/studiolights/matcap/metal_bronze.exr` | 39725 | `d11e4fc69d1559ea76a4d54131ca3c86ef201dd2cc4df28a6c735278736f96d5` |
| `release/datafiles/studiolights/matcap/metal_carpaint.exr` | 90142 | `a712cfa9d728ff7fea5e8c43cb84f080b941b68f229aacfd6c869b08047928ac` |
| `release/datafiles/studiolights/matcap/pearl.exr` | 72207 | `5c08e6385b84e49037fb72a441073a469f8a3332b9a9de6aed92703f5e280b96` |
| `release/datafiles/studiolights/matcap/red_wax.exr` | 144643 | `ff3e9c647952c9f5bedf33a82c91e4751b844b2e0f53dab29d4b01656ebe9722` |
| `release/datafiles/studiolights/matcap/resin.exr` | 81355 | `270f3aac15c471a3dc5a30ea5656fe29d55d608808bbcd0965bc1cc506a12ee5` |
| `release/datafiles/studiolights/matcap/toon_dark.exr` | 57592 | `cf786425d7e2989c89f5e9c67080f1504b71b22d434a6939a501bda992003a25` |
| `release/datafiles/studiolights/matcap/toon_light.exr` | 35044 | `6f67937b9a212c7e98e888a5e36b7823263ba581e2e00bcbac44813f6e27f162` |
| `release/datafiles/studiolights/world/city.exr` | 204863 | `9e42abcd2fa3231e5c2485ca6dd64800534d157b7194ab7fe9cc3bf5a56d0256` |
| `release/datafiles/studiolights/world/courtyard.exr` | 255126 | `6690b47725965531559380121e6878373eb599655e35fefd109a4bd0911366f3` |
| `release/datafiles/studiolights/world/forest.exr` | 552641 | `bdf2298244affa0f85509380fd130ac6d4dfaa3c856df065998f7f4c1a93dc0d` |
| `release/datafiles/studiolights/world/interior.exr` | 189416 | `e945ff5c1ddd7a3aaf05e9fb5c3bc9cb93c5518414febd44ed2c394e013f0cbd` |
| `release/datafiles/studiolights/world/night.exr` | 139959 | `17480af5547465d160f7307c92585cf30820ca563f87f066395decbad8ac32a4` |
| `release/datafiles/studiolights/world/studio.exr` | 98015 | `c36c7fd390b2cdf8693360cf3662cb1d710c95fa799d9f822f42997167839b56` |
| `release/datafiles/studiolights/world/sunrise.exr` | 251877 | `6a1180126e4db7d01f134c5430ea43c1b263ab1a12faf58a444d9ce9c03f3a84` |
| `release/datafiles/studiolights/world/sunset.exr` | 171164 | `3bcafdda4f2d7b9759cc1d73004d34d721a274c29b1a0947be88a602dbac426b` |
| `scripts/startup/bl_app_templates_system/2D_Animation/startup.blend` | 106329 | `48c4cc4f5785c6aafcab751f7558251c51c45a2cac7687dfbbbf39d339e3b3b2` |
| `scripts/startup/bl_app_templates_system/Sculpting/startup.blend` | 91933 | `332aefd6440dbc5555679218755b7536bd98154de7b4c73587d59b22907e8809` |
| `scripts/startup/bl_app_templates_system/Storyboarding/startup.blend` | 111491 | `f877d42562e190571949624302b403d673deb8580f63ec3e4f816f4a3f690190` |
| `scripts/startup/bl_app_templates_system/VFX/startup.blend` | 93140 | `740f8e2a86f1afafa274171f7727373cc66fb6de6cdda4d1458789a62c797005` |
| `scripts/startup/bl_app_templates_system/Video_Editing/startup.blend` | 81337 | `e44005e3c2b7a30055046e6fd60cdaf6799c22921679efa77b16d7cec889639e` |

</details>
