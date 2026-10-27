design /Users/atom/dev/gauntlet/docs/superpowers/specs/m2-launcher-kinds-design.md | order /Users/atom/dev/gauntlet/docs/superpowers/specs/m2-launcher-kinds-order-design.md | main bbedcc4
landed 1 | 07fdfb4
landed 2 | 07fdfb4
landed 3 | 07fdfb4
landed 3a | 383b8af
landed 3b | 383b8af
landed 3c | 383b8af
landed 3d | c0df7c4
landed 3e | c0df7c4
landed 3f | c0df7c4
landed 3g | d51322a
landed 4 | baa00d3
landed 5 | baa00d3
landed 7 | baa00d3
landed 8a | baa00d3
landed 8b | baa00d3
landed 8c | baa00d3
landed 8d | baa00d3
landed 8e | baa00d3
landed 9 | e1fa20c
landed 16 | 2a1125e
landed 17 | 2a1125e
landed 18 | 2a1125e
landed 24a | 8428708
landed 24b | 8428708
landed 24c | 8428708
section s1 | lead | steps: 10, 11, 12 | size: lead: tokens: 891719.5 seconds: 668.8 overruns: 0 refusals: 0
  s1.d1 | core-builder | steps: 10 | writes: gauntlet/core/launch.py | size: core-builder: tokens: 206419.9 seconds: 93.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s1.d1
    stub
    | 10 stub | core-builder | gauntlet/core/launch.py | Complete kind/plan contracts. |
    gauntlet/core/launch.py
  s1.d2 | test-writer | steps: 11 | writes: tests/test_core_launch.py | size: test-writer: tokens: 525778.4 seconds: 159.3 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s1.d2
    red
    design: docs/superpowers/specs/m2-launcher-kinds-design.md docs/superpowers/specs/m2-launcher-kinds-order-design.md 11
    behavior: Require tests of six independent literal kind tables and all hardening/network branches to fail against stubs.
    view: gauntlet/core/launch.py
  s1.d3 | core-builder | steps: 12 | writes: gauntlet/core/launch.py | size: core-builder: tokens: 206419.9 seconds: 93.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s1.d3
    | 12 build | core-builder | gauntlet/core/launch.py | Literal kind-table and hardening tests must pass; one policy per Kind. |
    tests/test_core_launch.py
    gauntlet/core/launch.py
section s2 | lead | steps: 13, 14, 15 | size: lead: tokens: 891719.5 seconds: 668.8 overruns: 0 refusals: 0
  s2.d1 | seamstress | steps: 13 | writes: gauntlet/seams/git.py | size: seamstress: tokens: 355717.4 seconds: 337.4 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s2.d1
    stub
    | 13 stub | seamstress | gauntlet/seams/git.py | Host git/worktree/observation interfaces. |
    gauntlet/seams/git.py
  s2.d2 | test-writer | steps: 14 | writes: tests/test_seams_git.py | size: test-writer: tokens: 525778.4 seconds: 159.3 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s2.d2
    red
    design: docs/superpowers/specs/m2-launcher-kinds-design.md docs/superpowers/specs/m2-launcher-kinds-order-design.md 14
    behavior: Require explicit-identity, job-lifecycle and intent-observation tests to fail against stubs
    view: gauntlet/seams/git.py
  s2.d3 | seamstress | steps: 15 | writes: gauntlet/seams/git.py | size: seamstress: tokens: 355717.4 seconds: 337.4 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s2.d3
    | 15 build | seamstress | gauntlet/seams/git.py | Explicit-identity, worktree-lifecycle and git-intent tests must pass. |
    tests/test_seams_git.py
    gauntlet/seams/git.py
section s3 | lead | steps: 18a, 18b, 18c | size: lead: tokens: 891719.5 seconds: 668.8 overruns: 0 refusals: 0
  s3.d1 | seamstress | steps: 18a | writes: gauntlet/seams/mounts.py | size: seamstress: tokens: 355717.4 seconds: 337.4 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s3.d1
    stub
    | 18a stub | seamstress | gauntlet/seams/mounts.py | Complete source-validation/staging interface. |
    gauntlet/seams/mounts.py
  s3.d2 | test-writer | steps: 18b | writes: tests/test_seams_mounts.py | size: test-writer: tokens: 525778.4 seconds: 159.3 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s3.d2
    red
    design: docs/superpowers/specs/m2-launcher-kinds-design.md docs/superpowers/specs/m2-launcher-kinds-order-design.md 18b
    behavior: Escapes, symlinks, missing protections, parent exclusion, explicit config staging and helper overlays fail against stubs.
    view: gauntlet/seams/mounts.py
  s3.d3 | seamstress | steps: 18c | writes: gauntlet/seams/mounts.py | size: seamstress: tokens: 355717.4 seconds: 337.4 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s3.d3
    | 18c build | seamstress | gauntlet/seams/mounts.py | Source-validation and minimal-tree tests must pass using JobStore-owned staging. |
    tests/test_seams_mounts.py
    gauntlet/seams/mounts.py
section s4 | lead | steps: 19, 20, 21 | size: lead: tokens: 891719.5 seconds: 668.8 overruns: 0 refusals: 0
  s4.d1 | seamstress | steps: 19 | writes: gauntlet/seams/images.py | size: seamstress: tokens: 355717.4 seconds: 337.4 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s4.d1
    stub
    | 19 stub | seamstress | gauntlet/seams/images.py | Complete ImagePreparation/ImageBuilder and build/refresh interfaces without a pin manifest. |
    gauntlet/seams/images.py
  s4.d2 | test-writer | steps: 20 | writes: tests/test_seams_images.py | size: test-writer: tokens: 525778.4 seconds: 159.3 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s4.d2
    red
    design: docs/superpowers/specs/m2-launcher-kinds-design.md docs/superpowers/specs/m2-launcher-kinds-order-design.md 20
    behavior: Current-version assembly, installed reuse, proxy isolation, missing-image acquisition and confirmed identities fail against stubs
    view: gauntlet/seams/images.py
  s4.d3 | seamstress | steps: 21 | writes: gauntlet/seams/images.py | size: seamstress: tokens: 355717.4 seconds: 337.4 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s4.d3
    | 21 build | seamstress | gauntlet/seams/images.py | Current/installed-version, image-isolation, acquisition-failure and confirmed-identity tests must pass. |
    tests/test_seams_images.py
    gauntlet/seams/images.py
section s5 | lead | steps: 22, 23, 24 | size: lead: tokens: 891719.5 seconds: 668.8 overruns: 0 refusals: 0
  s5.d1 | seamstress | steps: 22 | writes: gauntlet/seams/entrypoint.py, gauntlet/seams/readiness.py | size: seamstress: tokens: 355717.4 seconds: 337.4 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s5.d1
    stub
    | 22 stub | seamstress | gauntlet/seams/entrypoint.py, gauntlet/seams/readiness.py | Relay and readiness interfaces, adding the Readiness protocol with its first consumer. |
    gauntlet/seams/entrypoint.py
    gauntlet/seams/readiness.py
  s5.d2 | test-writer | steps: 23 | writes: tests/test_seams_entrypoint.py | size: test-writer: tokens: 525778.4 seconds: 159.3 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s5.d2
    red
    design: docs/superpowers/specs/m2-launcher-kinds-design.md docs/superpowers/specs/m2-launcher-kinds-order-design.md 23
    behavior: Relay-start callback, shared timeout, readiness-before-exec and failed-start cleanup fail against stubs.
    view: gauntlet/seams/entrypoint.py
  s5.d3 | seamstress | steps: 24 | writes: gauntlet/seams/entrypoint.py | size: seamstress: tokens: 355717.4 seconds: 337.4 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s5.d3
    | 24 build | seamstress | gauntlet/seams/entrypoint.py | Relay-start ordering, shared startup budget and cleanup tests must pass. |
    tests/test_seams_entrypoint.py
    gauntlet/seams/entrypoint.py
section s6 | lead | steps: 25, 26, 27, 28 | size: lead: tokens: 891719.5 seconds: 668.8 overruns: 0 refusals: 0
  s6.d1 | seamstress | steps: 25 | writes: gauntlet/seams/proxy.py | size: seamstress: tokens: 355717.4 seconds: 337.4 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s6.d1
    stub
    | 25 stub | seamstress | gauntlet/seams/proxy.py | Complete secret/HTTPS-forwarding interfaces using the fixed policy. |
    gauntlet/seams/proxy.py
  s6.d2 | test-writer | steps: 26 | writes: tests/test_seams_proxy.py | size: test-writer: tokens: 525778.4 seconds: 159.3 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s6.d2
    red
    design: docs/superpowers/specs/m2-launcher-kinds-design.md docs/superpowers/specs/m2-launcher-kinds-order-design.md 26
    behavior: Tests cover HTTPS routing to the fixed upstream, route-extension transport, redirects, default/overridden limits, invalid arguments, framing, streaming and secret isolation
    view: gauntlet/seams/proxy.py
  s6.d3 | seamstress | steps: 27 | writes: gauntlet/seams/proxy.py | size: seamstress: tokens: 355717.4 seconds: 337.4 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s6.d3
    | 27 build | seamstress | gauntlet/seams/proxy.py | HTTPS, framing, streaming, config limit/route transport and secret-isolation tests must pass. |
    tests/test_seams_proxy.py
    gauntlet/seams/proxy.py
  s6.d4 | gatesmith | steps: 28 | writes: pyproject.toml, uv.lock | size: gatesmith: tokens: 435361.5 seconds: 170.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s6.d4
    dependency
    claude-agent-sdk
    | 28 dependency | gatesmith | pyproject.toml, uv.lock | Resolve current SDK/HTTP releases into the installation lock; runtime accepts installed versions without exact release requirements. Land with importing adapters. |
  s6.d5 | gatesmith | steps: 28 | writes: pyproject.toml, uv.lock | size: gatesmith: tokens: 435361.5 seconds: 170.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s6.d5
    dependency
    httpx
    | 28 dependency | gatesmith | pyproject.toml, uv.lock | Resolve current SDK/HTTP releases into the installation lock; runtime accepts installed versions without exact release requirements. Land with importing adapters. |
section s7 | lead | steps: 28a, 28b, 28c | size: lead: tokens: 891719.5 seconds: 668.8 overruns: 0 refusals: 0
  s7.d1 | seamstress | steps: 28a | writes: gauntlet/seams/credentials.py | size: seamstress: tokens: 355717.4 seconds: 337.4 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s7.d1
    stub
    | 28a stub | seamstress | gauntlet/seams/credentials.py | Complete readable-descriptor source interfaces. |
    gauntlet/seams/credentials.py
  s7.d2 | test-writer | steps: 28b | writes: tests/test_seams_credentials.py | size: test-writer: tokens: 525778.4 seconds: 159.3 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s7.d2
    red
    design: docs/superpowers/specs/m2-launcher-kinds-design.md docs/superpowers/specs/m2-launcher-kinds-order-design.md 28b
    behavior: Duplicate/close ownership, invalid descriptors and no key in command text fail against stubs.
    view: gauntlet/seams/credentials.py
  s7.d3 | seamstress | steps: 28c | writes: gauntlet/seams/credentials.py | size: seamstress: tokens: 355717.4 seconds: 337.4 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s7.d3
    | 28c build | seamstress | gauntlet/seams/credentials.py | Descriptor ownership, validation and credential-isolation tests must pass. |
    tests/test_seams_credentials.py
    gauntlet/seams/credentials.py
section s8 | lead | steps: 29, 29a, 29c | size: lead: tokens: 891719.5 seconds: 668.8 overruns: 0 refusals: 0
  s8.d1 | seamstress | steps: 29 | writes: gauntlet/seams/launch.py | size: seamstress: tokens: 355717.4 seconds: 337.4 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s8.d1
    stub
    | 29 stub | seamstress | gauntlet/seams/launch.py | Complete SDK/lifecycle/recovery contracts, importing shared mount, credential and readiness homes. |
    gauntlet/seams/launch.py
  s8.d2 | test-writer | steps: 29a | writes: tests/support/process.py, tests/test_support_process.py | size: test-writer: tokens: 525778.4 seconds: 159.3 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s8.d2
    red
    design: docs/superpowers/specs/m2-launcher-kinds-design.md docs/superpowers/specs/m2-launcher-kinds-order-design.md 29a
    behavior: Raise-only FakeSdk contract and literal reply/call/exhaustion tests after launcher stubs
    view: gauntlet/seams/launch.py
  s8.d3 | test-writer | steps: 29c | writes: tests/support/process.py | size: test-writer: tokens: 525778.4 seconds: 159.3 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s8.d3
    port
    design: docs/superpowers/specs/m2-launcher-kinds-design.md docs/superpowers/specs/m2-launcher-kinds-order-design.md 29c
    files: tests/support/process.py
    view: gauntlet/seams/launch.py
    view: gauntlet/seams/process.py
    view: gauntlet/core/errors.py
    view: gauntlet/core/launch.py
section s9 | lead | steps: 30, 31, 31a, 32 | size: lead: tokens: 888124.9 seconds: 664.1 overruns: 0 refusals: 0
  s9.d1 | test-writer | steps: 30 | writes: tests/test_m2_contract.py | size: test-writer: tokens: 525778.4 seconds: 159.3 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s9.d1
    red
    design: docs/superpowers/specs/m2-launcher-kinds-design.md docs/superpowers/specs/m2-launcher-kinds-order-design.md 30
    behavior: its check compares complete mount and tool tables with no container started
    view: gauntlet/seams/launch.py
  s9.d2 | test-writer | steps: 31 | writes: tests/test_seams_launch.py | size: test-writer: tokens: 525778.4 seconds: 159.3 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s9.d2
    red
    design: docs/superpowers/specs/m2-launcher-kinds-design.md docs/superpowers/specs/m2-launcher-kinds-order-design.md 31
    behavior: Mount validation, image preparation before deadline/secret creation, pull-disabled runs, SDK options, proxy limits/routes, labels and cleanup fail against stubs.
    view: gauntlet/seams/launch.py
    behavior: Image-preparation events may exceed the startup budget without expiring it.
    view: gauntlet/seams/launch.py
  s9.d3 | test-writer | steps: 31a | writes: tests/test_seams_launch_recovery.py | size: test-writer: tokens: 525778.4 seconds: 159.3 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s9.d3
    red
    design: docs/superpowers/specs/m2-launcher-kinds-design.md docs/superpowers/specs/m2-launcher-kinds-order-design.md 31a
    behavior: Durable identities, contradictory ownership, structured absence and removal-before-restore/repeated-recovery tests fail against stubs.
    view: gauntlet/seams/launch.py
  s9.d4 | seamstress | steps: 32 | writes: gauntlet/seams/launch.py | size: seamstress: tokens: 355717.4 seconds: 337.4 overruns: 0 refusals: 0
    queue /Users/atom/dev/foreman/queues/m2-rest.md s9.d4
    | 32 build | seamstress | gauntlet/seams/launch.py | Six-kind assembly, launch and recovery tests must pass through shared planner, lifecycle and recovery helpers. |
    tests/test_m2_contract.py
    tests/test_seams_launch.py
    tests/test_seams_launch_recovery.py
    gauntlet/seams/launch.py
