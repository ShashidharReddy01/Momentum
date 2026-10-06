"""Phase 7.5 (spec §4.2): VBA macros, read **as text** with ``oletools.olevba``.

Macros are never executed, emulated or evaluated: olevba parses the VBA project's streams and
decompresses the source; its keyword analysis is reduced to plain English. Code is kept to
``MACRO_LINES`` lines per module in the model.
"""

from __future__ import annotations

import logging

from momentum.files.model import MacroFlag, MacroInfo, MacroModule

MACRO_LINES = 400
MAX_MODULES = 50

# olevba's keyword → what it means for a person (spec: auto-run, runs programs, downloads files,
# writes files, hides itself). Anything else olevba finds suspicious is reported in its words.
_RUNS = {"shell", "wscript.shell", "run", "shellexecute", "exec", "createobject", "callbyname"}
_DOWNLOADS = {
    "urldownloadtofile",
    "urldownloadtofilea",
    "msxml2.xmlhttp",
    "microsoft.xmlhttp",
    "winhttp.winhttprequest",
    "xmlhttp",
    "internetexplorer.application",
    "inet",
}
_WRITES = {
    "open",
    "write",
    "put",
    "print #",
    "savetofile",
    "kill",
    "filecopy",
    "copyfile",
    "createtextfile",
    "binary",
    "adodb.stream",
    "mkdir",
}
_HIDES = {"hide", "visible", "showwindow", "vbhide", "application.visible", "screenupdating"}


_OWN_SCAN: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("autoopen", "auto_open", "document_open", "workbook_open", "autoexec", "autoclose"),
        "Runs automatically when the file is opened or closed",
    ),
    (("shell", "wscript", "shellexecute", "createobject("), "Runs other programs or commands"),
    (
        ("urldownloadtofile", "xmlhttp", "winhttp", "internetexplorer"),
        "Downloads files from the internet",
    ),
    (
        ("kill ", "filecopy", "savetofile", "createtextfile", "for output as"),
        "Writes, copies or deletes files",
    ),
)


def _meaning(kind: str, keyword: str, description: str) -> str | None:
    k = keyword.lower()
    if kind == "AutoExec":
        return "Runs automatically when the file is opened or closed"
    if kind != "Suspicious":
        return None  # IOCs, hex strings etc. are reported only through the keywords above
    if k in _DOWNLOADS or "download" in k or "http" in k:
        return "Downloads files from the internet"
    if k in _RUNS:
        return "Runs other programs or commands"
    if k in _WRITES or "write to a file" in description.lower():
        return "Writes, copies or deletes files"
    if k in _HIDES:
        return "Hides itself or its windows"
    if "obfusc" in description.lower() or "hex" in k or "base64" in k:
        return None
    return description


def read_macros(data: bytes, filename: str) -> MacroInfo:
    from oletools.olevba import VBA_Parser

    logging.getLogger("olevba").setLevel(logging.CRITICAL)
    parser = VBA_Parser(filename, data=data)
    try:
        if not parser.detect_vba_macros():
            return MacroInfo(present=False)
        modules: list[MacroModule] = []
        for _f, stream, vba_name, code in parser.extract_macros():
            if len(modules) >= MAX_MODULES:
                break
            text = code if isinstance(code, str) else code.decode("latin-1", "replace")
            lines = text.splitlines()
            # skip the "Attribute VB_..." header lines VBA writes into every module
            body = [ln for ln in lines if not ln.startswith("Attribute VB_")]
            name = vba_name.rsplit(".", 1)[0] if vba_name else stream
            kind = {"bas": "module", "cls": "class", "frm": "form"}.get(
                vba_name.rsplit(".", 1)[-1].lower() if vba_name else "", "module"
            )
            if not any(ln.strip() for ln in body):
                continue  # an empty document/sheet module: nothing to report
            modules.append(
                MacroModule(
                    name=name, kind=kind, lines=len(body), code="\n".join(body[:MACRO_LINES])
                )
            )
        flags: dict[str, MacroFlag] = {}
        for kind, keyword, description in parser.analyze_macros() or []:
            meaning = _meaning(kind, keyword, description)
            if meaning is None:
                continue
            module = next((m.name for m in modules if keyword.lower() in m.code.lower()), None)
            if meaning in flags:  # one flag per meaning, listing every keyword behind it
                f = flags[meaning]
                if keyword.lower() not in f.keyword.lower().split(", "):
                    f.keyword = f"{f.keyword}, {keyword}"
                f.module = f.module or module
                continue
            flags[meaning] = MacroFlag(keyword=keyword, meaning=meaning, module=module)
        # olevba's analysis misses some calls when they aren't declared: our own word scan backs
        # it up for the four things a person must know about
        for words, meaning in _OWN_SCAN:
            for m in modules:
                low = m.code.lower()
                hit = next((w for w in words if w in low), None)
                if hit and meaning not in flags:
                    flags[meaning] = MacroFlag(keyword=hit, meaning=meaning, module=m.name)
        return MacroInfo(present=bool(modules), modules=modules, flags=list(flags.values()))
    finally:
        parser.close()
