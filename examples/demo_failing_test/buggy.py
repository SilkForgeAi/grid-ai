"""A tiny module with one deliberate bug, for the Grid AI live smoke test.

`add` should return the sum of two numbers, but it subtracts. The failing test in
test_buggy.py pins the correct behavior. Ask Grid AI to make the test pass and
watch it: run the test in its own terminal, read the failure, explain why it
broke (teaching mode), fix `add`, and re-run to green.
"""


def add(a, b):
    return a - b  # BUG: should be a + b
