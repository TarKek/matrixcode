import io
p = "ui/app.py"
s = io.open(p, encoding="utf-8").read()

# --- 1. alias /context for /ctx ---
old = '        if text == "/ctx":\n            if self.agent:'
assert s.count(old) == 1, ("ctx", s.count(old))
new = '        if text in ("/ctx", "/context"):\n            if self.agent:'
s = s.replace(old, new)

# --- 2. log registry command result ---
old2 = (
    "            entry = self.commands.commands.get(cmd)\n"
    "            if entry is not None:\n"
    "                try:\n"
    "                    out = entry[\"fn\"](self, arg)\n"
    "                    if asyncio.iscoroutine(out):\n"
    "                        out = await out\n"
    "                    if out:\n"
    "                        chat.add_system(out)\n"
    "                except Exception as e:\n"
    "                    chat.add_system(\n"
    "                        f\"command error: {type(e).__name__}: {e}\")\n"
    "                self.query_one(\"#prompt\", HistoryInput).focus()\n"
    "                return"
)
assert s.count(old2) == 1, ("reg", s.count(old2))
new2 = (
    "            entry = self.commands.commands.get(cmd)\n"
    "            if entry is not None:\n"
    "                try:\n"
    "                    out = entry[\"fn\"](self, arg)\n"
    "                    if asyncio.iscoroutine(out):\n"
    "                        out = await out\n"
    "                    if out:\n"
    "                        chat.add_system(out)\n"
    "                    self.logger.event(\"command\", cmd=cmd, arg=arg[:300],\n"
    "                                      out=str(out)[:800] if out else \"\",\n"
    "                                      ok=True)\n"
    "                except Exception as e:\n"
    "                    chat.add_system(\n"
    "                        f\"command error: {type(e).__name__}: {e}\")\n"
    "                    self.logger.event(\"command\", cmd=cmd, arg=arg[:300],\n"
    "                                      error=f\"{type(e).__name__}: {e}\",\n"
    "                                      ok=False)\n"
    "                self.query_one(\"#prompt\", HistoryInput).focus()\n"
    "                return"
)
s = s.replace(old2, new2)

# --- 3. log builtin /ctx ---
old3 = (
    '                    f"thinking={self._thinking_label()}")\n'
    '            return'
)
assert s.count(old3) == 1, ("ctxlog", s.count(old3))
new3 = (
    '                    f"thinking={self._thinking_label()}")\n'
    '                self.logger.event("command", cmd=text,\n'
    '                                  messages=len(self.agent.messages),\n'
    '                                  last_p=self.agent.last_prompt_tokens)\n'
    '            return'
)
s = s.replace(old3, new3)

# --- 4. log unknown slash-command ---
old4 = (
    "                self.query_one(\"#prompt\", HistoryInput).focus()\n"
    "                return\n\n"
    "        # 6."
)
assert s.count(old4) == 1, ("unk", s.count(old4))
new4 = (
    "                self.query_one(\"#prompt\", HistoryInput).focus()\n"
    "                return\n\n"
    "        # 6."
)
s = s.replace(old4, new4)

io.open(p, "w", encoding="utf-8").write(s)
print("patched app.py")
