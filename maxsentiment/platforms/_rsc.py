"""Read captured React Flight records without executing their contents."""
import json
import re

REFERENCE = re.compile(r"^\$(?:L|@|Q|W)?([0-9a-f]+)((?::[^:]*)*)$")
RECORD_ID = re.compile(rb"([0-9a-f]*):")
LENGTH_TAGS = set(b"TAOoUSsLlGgMmV")


class Flight:
    def __init__(self, raw):
        self.records = {}
        self.tags = {}
        self.errors = []
        self._index = None
        pos = 0
        while pos < len(raw):
            if raw[pos:pos+1] == b"\n":
                pos += 1
                continue
            match = RECORD_ID.match(raw, pos)
            if not match:
                self.errors.append({"offset": pos, "reason": "missing_record_id"})
                break
            key = match[1].decode()
            pos = match.end()
            if pos >= len(raw):
                break
            tag = raw[pos]
            if tag in LENGTH_TAGS:
                comma = raw.find(b",", pos)
                if comma < 0:
                    self.errors.append({"offset": pos, "reason": "missing_length"})
                    break
                try:
                    length = int(raw[pos+1:comma], 16)
                except ValueError:
                    self.errors.append({"offset": pos, "reason": "invalid_length"})
                    break
                start = comma + 1
                end = start + length
                content = raw[start:end]
                if end > len(raw):
                    self.errors.append({"offset": pos, "reason": "truncated_record"})
                    break
                self.records[key] = content.decode("utf-8") if tag == ord("T") else {"binary_bytes": len(content)}
                self.tags[key] = chr(tag)
                pos = end
                continue
            end = raw.find(b"\n", pos)
            if end < 0:
                end = len(raw)
            payload = raw[pos:end]
            if payload.startswith(b"H"):
                # Resource hints have no model value and may have an empty id.
                pos = end + 1
                continue
            record_tag = ""
            if payload[:1] in (b"I", b"E", b"D", b"H", b"J", b"W", b"N"):
                record_tag = payload[:1].decode()
                payload = payload[1:]
            try:
                self.records[key] = json.loads(payload)
                self.tags[key] = record_tag
            except (ValueError, UnicodeError):
                self.errors.append({"offset": pos, "record": key, "reason": "unsupported_record"})
            pos = end + 1

    def reference(self, value):
        if not isinstance(value, str) or not value.startswith("$"):
            return None
        match = REFERENCE.match(value)
        return (match[1], [p for p in match[2].split(":") if p]) if match else None

    def deref(self, value, limit=64):
        if not isinstance(value, str) or not value.startswith("$"):
            return value
        visited = set()
        for _ in range(limit):
            ref = self.reference(value)
            if not ref or value in visited:
                return value
            visited.add(value)
            key, path = ref
            if key not in self.records:
                return value
            result = self.records[key]
            try:
                for part in path:
                    result = self.deref(result)
                    if isinstance(result, list):
                        if len(result) >= 4 and result[0] == "$" and part in ("type", "key", "props"):
                            result = result[{"type": 1, "key": 2, "props": 3}[part]]
                        else:
                            result = result[int(part)]
                    else:
                        result = result[part]
            except (TypeError, IndexError, KeyError, ValueError):
                return value
            value = result
        return value

    def walk(self, value=None, follow=False):
        pending = [self.records if value is None else value]
        seen = set()
        while pending:
            node = pending.pop()
            if follow:
                node = self.deref(node)
            if isinstance(node, (dict, list)):
                if id(node) in seen:
                    continue
                seen.add(id(node))
            yield node
            if isinstance(node, dict):
                pending.extend(reversed(node.values()))
            elif isinstance(node, list):
                pending.extend(reversed(node))

    @property
    def index(self):
        if self._index is None:
            views = {}
            states, pagination, requests = [], [], []
            for node in self.walk():
                if isinstance(node, dict):
                    if "viewTrackingSpecs" in node:
                        spec = self.deref(node["viewTrackingSpecs"])
                        if isinstance(spec, dict):
                            views.setdefault(spec.get("viewName"), []).append(node)
                    if "modelStates" in node:
                        states.append(node)
                    if "nextPageRequest" in node:
                        pagination.append(self.deref(node["nextPageRequest"]))
                    if "requestId" in node:
                        requests.append(node)
                elif isinstance(node, str) and node.startswith("{"):
                    pagination.append(node)
            self._index = {"views": views, "states": states,
                           "pagination": pagination, "requests": requests}
        return self._index

    def views(self, name):
        return self.index["views"].get(name, ())

    def text(self, value):
        output = []
        def collect(node, stack):
            node = self.deref(node)
            if isinstance(node, str):
                if node.startswith("$$"):
                    output.append(node[1:])
                elif not node.startswith("$"):
                    output.append(node)
            elif isinstance(node, (dict, list)):
                if id(node) in stack:
                    return
                stack = stack | {id(node)}
                if isinstance(node, dict):
                    if "children" in node:
                        collect(node["children"], stack)
                    elif "textProps" in node:
                        collect(node["textProps"], stack)
                    elif "initialContent" in node:
                        collect(node["initialContent"], stack)
                elif len(node) >= 4 and node[0] == "$" and isinstance(node[3], dict):
                    if node[1] == "br":
                        output.append("\n")
                    else:
                        collect(node[3], stack)
                else:
                    for child in node:
                        collect(child, stack)
        collect(value, set())
        return "".join(output)
