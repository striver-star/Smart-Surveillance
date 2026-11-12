#!/usr/bin/env python3
"""Licence scan and SBOM for the HSS platform (task 23).

Reads the licence of every dependency we ship, checks it against the free and open-source
policy (Section 19, policy.json) and writes:
  docs/sbom/sbom.cdx.json     CycloneDX 1.5 software bill of materials
  docs/sbom/licence-report.md human-readable report

Sources:
  Python   each requirements file / pyproject, installed into a scratch folder for Linux x86_64,
           Python 3.12 (the version in our images); licence from the package metadata.
           Native libraries bundled in wheels (FFmpeg in PyAV and OpenCV) are checked for
           --enable-gpl / --enable-nonfree builds.
  Node     the WhatsApp gateway's package-lock.json, installed with `npm ci --omit=dev`.
  Go       `go list -m all` for the Wall Agent.
  Others   components.json: container images, models, datasets, build tools, exceptions.

Exit code 1 when something is denied, or unknown and not waived in waivers.json.
Engineering guidance, not legal advice.
Uses only the Python standard library.
"""
from __future__ import annotations

import argparse
import email.parser
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

PY_PROJECTS = {
    "api": "services/api/requirements.txt",
    "ai-worker": "services/ai-worker/requirements.txt",
    "probe": "tools/probe/pyproject.toml",
}
NODE_PROJECTS = {"whatsapp-gateway": "services/whatsapp-gateway"}
GO_PROJECTS = {"wall-agent": "services/wall-agent"}

# Free-text licence names -> SPDX ids. Checked in order; first match wins.
ALIASES = [
    (r"^(the )?mit( license)?$|^expat$|^mit/x11$", "MIT"),
    (r"^mit-0$|^mit no attribution", "MIT-0"),
    (r"apache( software)?( license)?[ ,-]*(version )?2(\.0)?|^apache-2\.0$|^apache 2$|^asl 2", "Apache-2.0"),
    (r"^apache software license$|^apache$|^apache license$", "Apache-2.0"),
    (r"^bsd[- ]?3|3-clause bsd|new bsd|modified bsd|^bsd license \(3", "BSD-3-Clause"),
    (r"^bsd[- ]?2|2-clause bsd|simplified bsd|freebsd", "BSD-2-Clause"),
    (r"^0bsd$", "0BSD"),
    (r"^bsd( license)?$", "BSD-3-Clause"),
    (r"^isc( license)?( \(iscl\))?$", "ISC"),
    (r"mozilla public license 2\.0|^mpl[- ]?2\.0", "MPL-2.0"),
    (r"^psf|python software foundation", "PSF-2.0"),
    (r"^unlicense$|the unlicense", "Unlicense"),
    (r"^zlib|zlib/libpng", "Zlib"),
    (r"^cc0|public domain", "CC0-1.0"),
    (r"^blueoak-1\.0\.0$", "BlueOak-1.0.0"),
    (r"^wtfpl$", "WTFPL"),
    (r"^lgpl-?2\.1\+?$|gnu lesser general public license v2\.1|lgplv2\.1", "LGPL-2.1-or-later"),
    (r"^lgpl-?3\.0?\+?$|gnu lesser general public license v3|lgplv3", "LGPL-3.0-or-later"),
    (r"^lgpl", "LGPL-2.1-or-later"),
    (r"^agpl|affero", "AGPL-3.0-or-later"),
    (r"^gpl-?3|gnu general public license v3|gplv3", "GPL-3.0-or-later"),
    (r"^gpl-?2|gnu general public license v2|gplv2", "GPL-2.0-or-later"),
    (r"^gpl$|gnu general public license", "GPL-3.0-or-later"),
    (r"sspl|server side public", "SSPL-1.0"),
    (r"business source", "BUSL-1.1"),
    (r"non[- ]?commercial|by-nc", "Non-commercial"),
]
CLASSIFIER = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: BSD License": "BSD-3-Clause",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.1-or-later",
    "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    "License :: OSI Approved :: GNU General Public License v3 (GPLv3)": "GPL-3.0-only",
    "License :: OSI Approved :: GNU General Public License v2 (GPLv2)": "GPL-2.0-only",
    "License :: OSI Approved :: GNU Affero General Public License v3": "AGPL-3.0-only",
    "License :: Public Domain": "CC0-1.0",
}
SPDX_LIKE = re.compile(r"^[A-Za-z0-9.+-]+$")


@dataclass
class Component:
    ecosystem: str             # pypi | npm | golang | image | model | dataset | ...
    name: str
    version: str
    licence: str               # SPDX expression, or "UNKNOWN"
    used_by: list[str] = field(default_factory=list)
    linked: bool = True        # True: loaded into our process (library); False: separate program
    use: str = ""
    source: str = ""
    note: str = ""
    status: str = ""           # ok | conditional | denied | unknown | waived
    reason: str = ""

    @property
    def key(self) -> str:
        return f"{self.ecosystem}:{self.name}"


# ---------------------------------------------------------------------------- licences

def normalise(text: str) -> str:
    """One licence name -> SPDX id (or the input, stripped, when it already looks like one)."""
    t = " ".join(text.strip().split())
    if not t:
        return "UNKNOWN"
    for pattern, spdx in ALIASES:
        if re.search(pattern, t, re.I):
            return spdx
    return t if SPDX_LIKE.match(t) else "UNKNOWN"


def normalise_expression(expr: str) -> str:
    """'MIT OR Apache-2.0', '(BSD-3-Clause AND MIT)', 'MIT/Apache 2.0' -> normalised SPDX expression."""
    expr = expr.strip().strip("()")
    if not expr:
        return "UNKNOWN"
    if re.fullmatch(r"[^;/]*(?: (?:OR|AND|WITH) [^;/]*)+", expr):
        parts = re.split(r" (OR|AND|WITH) ", expr)
        out = [p if p in ("OR", "AND", "WITH") else (p.strip("() ") if i and parts[i - 1] == "WITH"
                                                     else normalise(p.strip("() ")))
               for i, p in enumerate(parts)]
        return " ".join(out)
    if "/" in expr or ";" in expr:
        alts = [normalise(p) for p in re.split(r"[/;]", expr) if p.strip()]
        return " OR ".join(dict.fromkeys(alts))
    return normalise(expr)


def classify(licence: str, linked: bool, policy: dict) -> tuple[str, str]:
    """Return (status, reason) for an SPDX expression.

    OR: the best option counts (we may choose). AND: the worst part counts.
    A GPL/AGPL licence on a library we load into our own process is denied; on a separate
    program it is conditional.
    """
    if " OR " in licence:
        results = [classify(p, linked, policy) for p in licence.split(" OR ")]
        return min(results, key=lambda r: RANK[r[0]])
    if " AND " in licence:
        results = [classify(p, linked, policy) for p in licence.split(" AND ")]
        return max(results, key=lambda r: RANK[r[0]])
    lic = licence.split(" WITH ")[0].strip("() ")
    if lic in policy["denied"]:
        return "denied", f"{lic} is not allowed (Section 19)"
    if lic in policy["allowed"]:
        return "ok", ""
    if lic in policy["conditional"]:
        if linked and re.match(r"A?GPL-", lic):
            return "denied", f"{lic} library loaded into our code; GPL is allowed only as a separate program"
        return "conditional", policy["conditional"][lic]
    return "unknown", f"licence '{licence}' needs a manual check"


RANK = {"ok": 0, "waived": 1, "conditional": 2, "unknown": 3, "denied": 4}


# ---------------------------------------------------------------------------- Python

def python_licence(meta: email.message.Message) -> str:
    if meta.get("License-Expression"):
        return normalise_expression(meta["License-Expression"])
    found = [CLASSIFIER[c] for c in meta.get_all("Classifier", []) if c in CLASSIFIER]
    if found:
        return " OR ".join(dict.fromkeys(found))
    lic = (meta.get("License") or "").strip()
    if lic and "\n" not in lic and len(lic) < 80:
        return normalise_expression(lic)
    if lic:  # full licence text pasted into the field
        first = lic.splitlines()[0]
        for probe in (first, lic[:400]):
            n = normalise(probe)
            if n != "UNKNOWN":
                return n
        if "Permission is hereby granted, free of charge" in lic:
            return "MIT"
        if "Redistribution and use in source and binary forms" in lic:
            return "BSD-3-Clause"
    return "UNKNOWN"


def requirements_of(path: Path) -> list[str]:
    if path.suffix == ".toml":
        text = path.read_text()
        m = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
        return re.findall(r'"([^"]+)"', m.group(1)) if m else []
    return [line.split("#")[0].strip() for line in path.read_text().splitlines()
            if line.split("#")[0].strip()]


def install_python(reqs: list[str], target: Path) -> None:
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-compile",
           "--target", str(target), "--only-binary=:all:", "--python-version", "3.12",
           "--implementation", "cp", "--abi", "cp312", "--no-warn-conflicts"]
    for plat in ("manylinux_2_28_x86_64", "manylinux_2_17_x86_64", "manylinux2014_x86_64", "linux_x86_64"):
        cmd += ["--platform", plat]
    subprocess.run(cmd + reqs, check=True)


# Native libraries that are GPL-only. Finding one inside a wheel means GPL code is loaded into our
# process, whatever the Python package's own licence says.
GPL_LIBS = {"libx264": "GPL-2.0-or-later", "libx265": "GPL-2.0-or-later", "libpostproc": "GPL-2.0-or-later",
            "librubberband": "GPL-2.0-or-later", "libxvidcore": "GPL-2.0-or-later", "libvidstab": "GPL-2.0-or-later",
            "libfdk-aac": "Non-commercial"}
AVCODEC_LICENCE = {"LGPL version 2.1 or later": "LGPL-2.1-or-later", "LGPL version 3 or later": "LGPL-3.0-or-later",
                   "GPL version 2 or later": "GPL-2.0-or-later", "GPL version 3 or later": "GPL-3.0-or-later",
                   "nonfree and unredistributable": "Non-commercial"}


def bundled_native(target: Path) -> list[Component]:
    """FFmpeg builds and GPL libraries that wheels bundle in their `<pkg>.libs` folders."""
    comps = []
    for libdir in sorted(target.glob("*.libs")):
        owner = libdir.name.removesuffix(".libs").replace("_", "-")
        for lib in sorted(libdir.iterdir()):
            base = re.split(r"-[0-9a-f]{8}|\.so", lib.name)[0]
            if base == "libavcodec":
                m = re.search(rb"libavcodec license: ([A-Za-z0-9 .]+)", lib.read_bytes())
                text = m.group(1).decode().strip() if m else "unknown"
                comps.append(Component("bundled", f"FFmpeg (inside {owner})", "", AVCODEC_LICENCE.get(text, "UNKNOWN"),
                                       use="Video library inside the Python wheel",
                                       source="https://ffmpeg.org/legal.html", note=f"libavcodec reports: {text}"))
            elif base in GPL_LIBS:
                comps.append(Component("bundled", f"{base} (inside {owner})", "", GPL_LIBS[base],
                                       use="Native library inside the Python wheel", note=lib.name))
    return comps


def scan_python(policy: dict, work: Path) -> tuple[list[Component], list[str]]:
    comps: dict[str, Component] = {}
    notes = []
    for project, rel in PY_PROJECTS.items():
        target = work / f"py-{project}"
        install_python(requirements_of(ROOT / rel), target)
        for dist in sorted(target.glob("*.dist-info")):
            meta = email.parser.Parser().parsestr((dist / "METADATA").read_text(errors="replace"))
            name = meta["Name"].lower().replace("_", "-")
            c = comps.get(name) or Component("pypi", name, meta["Version"], python_licence(meta),
                                             source=f"https://pypi.org/project/{name}/{meta['Version']}/")
            c.used_by.append(project)
            comps[name] = c
        for c in bundled_native(target):
            c = comps.setdefault(c.key, c)
            c.used_by.append(project)
            line = f"{project}: {c.name}: {c.licence} ({c.note})"
            if line not in notes:
                notes.append(line)
    return list(comps.values()), notes


# ---------------------------------------------------------------------------- Node

def node_licence(pkg: dict) -> str:
    lic = pkg.get("license")
    if isinstance(lic, dict):
        lic = lic.get("type", "")
    if not lic and isinstance(pkg.get("licenses"), list):
        lic = " OR ".join(x.get("type", "") if isinstance(x, dict) else str(x) for x in pkg["licenses"])
    return normalise_expression(lic or "")


def scan_node(work: Path) -> list[Component]:
    comps = []
    for project, rel in NODE_PROJECTS.items():
        src = ROOT / rel
        dest = work / f"node-{project}"
        dest.mkdir(parents=True, exist_ok=True)
        for f in ("package.json", "package-lock.json"):
            (dest / f).write_bytes((src / f).read_bytes())
        env = dict(os.environ, PUPPETEER_SKIP_DOWNLOAD="1", PUPPETEER_SKIP_CHROMIUM_DOWNLOAD="1")
        subprocess.run(["npm", "ci", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund", "--silent"],
                       cwd=dest, check=True, env=env)
        lock = json.loads((dest / "package-lock.json").read_text())
        for path, info in sorted(lock.get("packages", {}).items()):
            if not path or info.get("dev"):
                continue
            pj = dest / path / "package.json"
            if not pj.exists():          # optional package for another platform
                continue
            pkg = json.loads(pj.read_text())
            name = pkg.get("name") or path.split("node_modules/")[-1]
            comps.append(Component("npm", name, pkg.get("version", info.get("version", "")), node_licence(pkg),
                                   [project], source=f"https://www.npmjs.com/package/{name}/v/{pkg.get('version', '')}"))
    # the same package can appear twice (nested versions): keep one entry per name@version
    unique = {}
    for c in comps:
        unique.setdefault((c.name, c.version), c)
    return list(unique.values())


# ---------------------------------------------------------------------------- Go

def scan_go() -> list[Component]:
    comps = []
    for project, rel in GO_PROJECTS.items():
        out = subprocess.run(["go", "list", "-m", "-json", "all"], cwd=ROOT / rel, check=True,
                             capture_output=True, text=True).stdout
        for block in re.findall(r"\{.*?\n\}", out, re.S):
            mod = json.loads(block)
            if mod.get("Main"):
                continue
            lic = "UNKNOWN"
            if mod.get("Dir"):
                for f in Path(mod["Dir"]).glob("LICEN[CS]E*"):
                    lic = licence_from_text(f.read_text(errors="replace"))
            comps.append(Component("golang", mod["Path"], mod.get("Version", ""), lic, [project]))
    return comps


def licence_from_text(text: str) -> str:
    t = text[:3000]
    if "Apache License" in t and "Version 2.0" in t:
        return "Apache-2.0"
    if "Permission is hereby granted, free of charge" in t:
        return "MIT"
    if "Redistribution and use in source and binary forms" in t:
        return "BSD-3-Clause" if "Neither the name" in t or "names of its" in t else "BSD-2-Clause"
    if "Mozilla Public License Version 2.0" in t:
        return "MPL-2.0"
    if "Permission to use, copy, modify, and/or distribute this software" in t:
        return "ISC"
    return "UNKNOWN"


# ---------------------------------------------------------------------------- others

def manual_components() -> list[Component]:
    data = json.loads((HERE / "components.json").read_text())
    return [Component(c["kind"], c["name"], c["version"], c["licence"], linked=False, use=c.get("use", ""),
                      source=c.get("source", ""), note=c.get("note", "") + (f" (checked {c['checked']})"
                                                                           if c.get("checked") else ""))
            for c in data["components"]]


# ---------------------------------------------------------------------------- output

def apply_policy(comps: list[Component], policy: dict, waivers: dict) -> None:
    for c in comps:
        c.status, c.reason = classify(c.licence, c.linked, policy)
        w = waivers.get(c.key) or waivers.get(f"{c.key}@{c.version}")
        if w and c.status in ("unknown", "denied"):
            c.status, c.reason = "waived", w


def cyclonedx(comps: list[Component]) -> dict:
    def purl(c: Component) -> str:
        if c.ecosystem == "pypi":
            return f"pkg:pypi/{c.name}@{c.version}"
        if c.ecosystem == "npm":
            n = c.name.replace("@", "%40", 1) if c.name.startswith("@") else c.name
            return f"pkg:npm/{n}@{c.version}"
        if c.ecosystem == "golang":
            return f"pkg:golang/{c.name}@{c.version}"
        return ""
    items = []
    for c in comps:
        item = {"type": {"model": "machine-learning-model", "dataset": "data", "media": "data",
                         "image": "container"}.get(c.ecosystem, "library"),
                "name": c.name, "version": c.version, "group": c.ecosystem,
                "licenses": [{"expression": c.licence}] if c.licence != "UNKNOWN" else [],
                "properties": [{"name": "hss:status", "value": c.status},
                               {"name": "hss:used-by", "value": ", ".join(sorted(set(c.used_by)))}]}
        if purl(c):
            item["purl"] = purl(c)
        if c.source.startswith("http"):
            item["externalReferences"] = [{"type": "website", "url": c.source}]
        items.append(item)
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
            "metadata": {"timestamp": f"{date.today()}T00:00:00Z",
                         "component": {"type": "application", "name": "HSS platform (proof of concept)"},
                         "tools": [{"name": "tools/licence-scan/scan.py"}]},
            "components": items}


def report(comps: list[Component], notes: list[str], fail: bool) -> str:
    counts = {s: sum(c.status == s for c in comps) for s in RANK}
    lines = [
        "# Licence scan and SBOM (task 23)", "",
        f"Generated {date.today()} by `tools/licence-scan/scan.py`. "
        "Engineering guidance against Section 19, not legal advice.", "",
        f"**Result: {'FAIL' if fail else 'PASS'}.** {len(comps)} components: "
        + ", ".join(f"{n} {s}" for s, n in counts.items() if n) + ".", "",
        "Status meanings: **ok** permissive licence; **conditional** allowed under the condition shown "
        "(LGPL library used unmodified, GPL program run separately, or a declared exception); "
        "**waived** checked by hand, see waivers.json; **unknown** needs a manual check; "
        "**denied** not allowed.", "",
    ]
    if notes:
        lines += ["## Native libraries inside Python wheels", ""] + [f"- {n}" for n in notes] + [""]
    flagged = [c for c in comps if c.status in ("denied", "unknown", "conditional", "waived")]
    if flagged:
        lines += ["## Needs attention or carries a condition", "",
                  "| Component | Version | Licence | Status | Why |", "| --- | --- | --- | --- | --- |"]
        for c in sorted(flagged, key=lambda c: (-RANK[c.status], c.ecosystem, c.name)):
            lines.append(f"| {c.ecosystem}: {c.name} | {c.version} | {c.licence} | {c.status} | "
                         f"{(c.reason + ' ' + c.note).strip()} |")
        lines.append("")
    by_lic: dict[str, int] = {}
    for c in comps:
        by_lic[c.licence] = by_lic.get(c.licence, 0) + 1
    lines += ["## Licences in use", "", "| Licence | Components |", "| --- | --- |"]
    lines += [f"| {lic} | {n} |" for lic, n in sorted(by_lic.items(), key=lambda x: -x[1])]
    lines += ["", "## All components", "", "| Type | Name | Version | Licence | Status | Used by / use |",
              "| --- | --- | --- | --- | --- | --- |"]
    for c in sorted(comps, key=lambda c: (c.ecosystem, c.name.lower())):
        lines.append(f"| {c.ecosystem} | {c.name} | {c.version} | {c.licence} | {c.status} | "
                     f"{', '.join(sorted(set(c.used_by))) or c.use} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(ROOT / "docs" / "sbom"), help="output folder")
    ap.add_argument("--skip", action="append", default=[], choices=["python", "node", "go"],
                    help="skip an ecosystem (for example when offline)")
    args = ap.parse_args(argv)
    policy = json.loads((HERE / "policy.json").read_text())
    waivers = json.loads((HERE / "waivers.json").read_text()) if (HERE / "waivers.json").exists() else {}
    waivers = {k: v for k, v in waivers.items() if not k.startswith("_")}
    comps: list[Component] = []
    notes: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        if "python" not in args.skip:
            py, notes = scan_python(policy, work)
            comps += py
        if "node" not in args.skip:
            comps += scan_node(work)
        if "go" not in args.skip:
            comps += scan_go()
    comps += manual_components()
    apply_policy(comps, policy, waivers)
    fail = any(c.status in ("denied", "unknown") for c in comps)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "sbom.cdx.json").write_text(json.dumps(cyclonedx(comps), indent=1) + "\n")
    (out / "licence-report.md").write_text(report(comps, notes, fail))
    for c in comps:
        if c.status in ("denied", "unknown"):
            print(f"{c.status.upper():8} {c.key}@{c.version}: {c.licence}  {c.reason}")
    print(f"{'FAIL' if fail else 'PASS'}: {len(comps)} components, report in {out / 'licence-report.md'}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
