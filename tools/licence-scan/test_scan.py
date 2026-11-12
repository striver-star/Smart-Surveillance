import json
from pathlib import Path

import scan

POLICY = json.loads((Path(scan.__file__).parent / "policy.json").read_text())


def test_normalise_common_names():
    assert scan.normalise("MIT License") == "MIT"
    assert scan.normalise("Apache Software License") == "Apache-2.0"
    assert scan.normalise("Apache License, Version 2.0") == "Apache-2.0"
    assert scan.normalise("BSD") == "BSD-3-Clause"
    assert scan.normalise_expression("MIT/Apache 2.0") == "MIT OR Apache-2.0"
    assert scan.normalise_expression("(BSD-3-Clause AND MIT)") == "BSD-3-Clause AND MIT"
    assert scan.normalise_expression("Apache-2.0 WITH LLVM-exception") == "Apache-2.0 WITH LLVM-exception"
    assert scan.normalise("") == "UNKNOWN"


def test_policy_rules():
    assert scan.classify("MIT", True, POLICY)[0] == "ok"
    assert scan.classify("LGPL-3.0-only", True, POLICY)[0] == "conditional"
    assert scan.classify("GPL-3.0-only", True, POLICY)[0] == "denied", "GPL library inside our process"
    assert scan.classify("GPL-2.0-or-later", False, POLICY)[0] == "conditional", "GPL as a separate program"
    assert scan.classify("GPL-3.0-only OR MIT", True, POLICY)[0] == "ok", "we may pick MIT"
    assert scan.classify("MIT AND GPL-3.0-only", True, POLICY)[0] == "denied"
    assert scan.classify("SSPL-1.0", False, POLICY)[0] == "denied"
    assert scan.classify("Non-commercial", False, POLICY)[0] == "denied"
    assert scan.classify("Some-Odd-Licence", True, POLICY)[0] == "unknown"


def test_bundled_gpl_libraries_are_caught(tmp_path):
    """The PyAV 19 wheel case: LGPL FFmpeg, but GPL x264 and x265 next to it."""
    libs = tmp_path / "av.libs"
    libs.mkdir()
    (libs / "libavcodec-d61378e8.so.63.1.102").write_bytes(b"\0libavcodec license: LGPL version 3 or later\0")
    (libs / "libx264-d6533a8d.so.165").write_bytes(b"")
    (libs / "libx265-eebb7db1.so.217").write_bytes(b"")
    found = {c.name: c for c in scan.bundled_native(tmp_path)}
    assert found["FFmpeg (inside av)"].licence == "LGPL-3.0-or-later"
    scan.apply_policy(list(found.values()), POLICY, {})
    assert found["libx264 (inside av)"].status == "denied"
    assert found["libx265 (inside av)"].status == "denied"


def test_waiver_needs_exact_key():
    c = scan.Component("npm", "odd-pkg", "1.0.0", "UNKNOWN")
    scan.apply_policy([c], POLICY, {"npm:odd-pkg": "checked LICENSE file by hand: MIT"})
    assert c.status == "waived"
