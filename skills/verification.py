"""verification — проверка результата после каждого тул-колла."""


# проверка результата после тула
def register(reg):
    reg.add("verification", """
After every <result>, briefly check:
  1. Did it match expectation? On error — what failed, how to fix.
  2. "exit=0" with empty output is NOT success.
  3. write_file "ok" means disk write, not correct content — for
     multi-file tasks verify with read_file / list_dir.
If it's wrong, STOP the plan, correct course, then continue.
""".strip())
