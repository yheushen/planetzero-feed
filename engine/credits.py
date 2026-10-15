"""Each source's required credit line (engine/schema/credits.json, from the terms checks of 15 Oct 2026), for the credit block
in every public JSON and for ATTRIBUTION.md. `python engine/credits.py` writes the repository's ATTRIBUTION.md, which evals/feed
(F11) checks is the same as the one written with every feed."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CREDITS = json.load(open(os.path.join(HERE, "schema", "credits.json"), encoding="utf-8"))
ALL = tuple(CREDITS["sources"])


def day(now):
    return f"{now.day} {now.strftime('%b')} {now.year}"


def line(source, now=None):
    text = CREDITS["sources"][source]["line"]
    return text.replace("{date}", day(now) if now else "the date given in each file")


def block(sources, now, ours=()):
    """{source: its credit line} for each source a file holds, in a fixed order, and our own notes."""
    out = {s: line(s, now) for s in ALL if s in sources}
    out.update({k: CREDITS["ours"][k] for k in ours})
    return out


def attribution_md():
    parts = ["# Attribution", "",
             "Planet Zero's feed holds data from these sources, each under its own terms, checked on "
             f"{CREDITS['checked']}. Every JSON file also carries a `credits` block for the sources it holds, with the date the data was "
             "fetched. Nobody downloading these files gets more rights than each source grants: see each licence.", ""]
    for s in ALL:
        c = CREDITS["sources"][s]
        parts += [f"## {c['name']}", "", line(s), "", f"Licence: {c['licence']}. {c['terms']}", ""]
    parts += ["## Ours", "", CREDITS["ours"]["checks"], "", CREDITS["ours"]["advice"], ""]
    return "\n".join(parts)


if __name__ == "__main__":
    root = os.path.dirname(HERE)
    with open(os.path.join(root, "ATTRIBUTION.md"), "w", encoding="utf-8") as f:
        f.write(attribution_md())
    print("wrote ATTRIBUTION.md")
