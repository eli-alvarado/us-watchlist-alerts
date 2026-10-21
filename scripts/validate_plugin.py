"""Validate ``.claude-plugin/plugin.json`` and ``marketplace.json`` against the
official Claude Code plugin/marketplace shape (offline; no Claude CLI).

python3 scripts/validate_plugin.py
"""
from __future__ import annotations
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HTTP = re.compile(r"^https?://\S+$")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _err(errors, msg):
    errors.append(msg)


def validate_plugin(data, errors, path="plugin.json"):
    if not isinstance(data, dict):
        _err(errors, f"{path}: root must be an object")
        return
    name = data.get("name")
    if not isinstance(name, str) or not KEBAB.match(name):
        _err(errors, f"{path}: name must be kebab-case (got {name!r})")
    elif name.startswith("claude-"):
        _err(errors, f"{path}: name must not start with 'claude-'")
    ver = data.get("version")
    if ver is not None and not isinstance(ver, str):
        _err(errors, f"{path}: version must be a string")
    homepage = data.get("homepage")
    if homepage is not None and not (isinstance(homepage, str) and HTTP.match(homepage)):
        _err(errors, f"{path}: homepage must be a valid URL")
    for url_key in ("documentationUrl", "supportUrl"):
        val = data.get(url_key)
        if val is not None and not (isinstance(val, str) and HTTP.match(val)):
            _err(errors, f"{path}: {url_key} must be a valid URL")
    author = data.get("author")
    if author is not None:
        if not isinstance(author, dict) or not author.get("name"):
            _err(errors, f"{path}: author must be an object with name")
    keywords = data.get("keywords")
    if keywords is not None and (
        not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords)
    ):
        _err(errors, f"{path}: keywords must be an array of strings")
    servers = data.get("mcpServers")
    if servers is not None:
        if not isinstance(servers, dict) or not servers:
            _err(errors, f"{path}: mcpServers must be a non-empty object")
        else:
            for sname, spec in servers.items():
                if not isinstance(sname, str) or not KEBAB.match(sname):
                    _err(errors, f"{path}: mcpServers key {sname!r} must be kebab-case")
                if not isinstance(spec, dict) or not isinstance(spec.get("command"), str):
                    _err(errors, f"{path}: mcpServers.{sname} needs command (string)")
                    continue
                args = spec.get("args")
                if args is not None and not (
                    isinstance(args, list) and all(isinstance(a, str) for a in args)
                ):
                    _err(errors, f"{path}: mcpServers.{sname}.args must be an array of strings")
                    continue
                for a in args or []:
                    rel = a.replace("${CLAUDE_PLUGIN_ROOT}", ROOT)
                    if rel.endswith(".py") and not os.path.isfile(rel):
                        _err(errors, f"{path}: mcpServers.{sname} script missing: {rel}")


def validate_marketplace(data, errors, path="marketplace.json"):
    if not isinstance(data, dict):
        _err(errors, f"{path}: root must be an object")
        return
    if not isinstance(data.get("name"), str) or not KEBAB.match(data["name"]):
        _err(errors, f"{path}: name is required (kebab-case)")
    owner = data.get("owner")
    if not isinstance(owner, dict) or not owner.get("name"):
        _err(errors, f"{path}: owner.name is required")
    plugins = data.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        _err(errors, f"{path}: plugins[] is required and must be non-empty")
        return
    for i, p in enumerate(plugins):
        loc = f"{path}: plugins[{i}]"
        if not isinstance(p, dict):
            _err(errors, f"{loc}: must be an object")
            continue
        if not isinstance(p.get("name"), str) or not KEBAB.match(p["name"]):
            _err(errors, f"{loc}: name is required (kebab-case)")
        src = p.get("source")
        if isinstance(src, str):
            if not src or src.startswith("/") or ".." in src.split("/"):
                _err(errors, f"{loc}: source path must be relative and must not contain '..'")
        elif isinstance(src, dict):
            if src.get("source") not in ("github", "git-subdir"):
                _err(errors, f"{loc}: source object needs source=github|git-subdir")
        else:
            _err(errors, f"{loc}: source is required (relative path or object)")
        if p.get("version") is not None and not isinstance(p["version"], str):
            _err(errors, f"{loc}: version must be a string")


def validate_tree(root=None):
    root = root or ROOT
    errors = []
    plugin_path = os.path.join(root, ".claude-plugin", "plugin.json")
    market_path = os.path.join(root, ".claude-plugin", "marketplace.json")
    if not os.path.isfile(plugin_path):
        errors.append("missing .claude-plugin/plugin.json")
        return errors
    if not os.path.isfile(market_path):
        errors.append("missing .claude-plugin/marketplace.json")
        return errors
    try:
        plugin = _load(plugin_path)
    except json.JSONDecodeError as e:
        return [f"plugin.json: not valid JSON ({e})"]
    try:
        market = _load(market_path)
    except json.JSONDecodeError as e:
        return [f"marketplace.json: not valid JSON ({e})"]
    validate_plugin(plugin, errors, ".claude-plugin/plugin.json")
    validate_marketplace(market, errors, ".claude-plugin/marketplace.json")
    plugins = market.get("plugins") if isinstance(market, dict) else None
    if isinstance(plugins, list) and plugins and isinstance(plugins[0], dict):
        if plugin.get("name") != plugins[0].get("name"):
            errors.append("plugin.json name must equal marketplace plugins[0].name")
        if plugin.get("name") != market.get("name"):
            errors.append("plugin.json name must equal marketplace.json name")
        versions = {
            "plugin.json": plugin.get("version"),
            "marketplace metadata": (market.get("metadata") or {}).get("version"),
            "marketplace plugin": plugins[0].get("version"),
        }
        present = {k: v for k, v in versions.items() if v}
        if len(set(present.values())) > 1:
            errors.append(f"version mismatch: {present}")
    server_path = os.path.join(root, "server.json")
    if os.path.isfile(server_path):
        try:
            server = _load(server_path)
        except json.JSONDecodeError as e:
            errors.append(f"server.json: not valid JSON ({e})")
        else:
            if not isinstance(server, dict) or not server.get("name") or not server.get("version"):
                errors.append("server.json: name and version are required")
            elif plugin.get("version") and server.get("version") != plugin.get("version"):
                errors.append(
                    f"server.json version {server.get('version')!r} != plugin.json {plugin.get('version')!r}"
                )
    return errors


def main(argv=None):
    root = ROOT
    if argv and argv[0] not in ("-h", "--help"):
        root = argv[0]
    elif argv:
        print(__doc__.strip())
        return 0
    errors = validate_tree(root)
    if errors:
        print("plugin schema: FAIL", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1
    print("plugin schema: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
