"""planning — план для многошаговых задач и трекинг шагов."""


# план для многошаговых задач
def register(reg):
    reg.add("planning", """
For a task that needs more than one tool call, START your reply with a
short numbered plan (plain lines, no code fence). After you receive a
<result> that starts with "ok:", that step is DONE — do NOT re-emit the
plan, move to the next step. Never call the same tool with the same
arguments twice. When all steps are done, end with a one-line summary.
For trivial single-step tasks, skip the plan and act directly.
""".strip())
