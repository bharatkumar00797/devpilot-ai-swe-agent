# add() returns the wrong result

`add(2, 3)` returns `-1` instead of `5`. The `test_add` test is failing.

Looking at `calculator.py`, it seems `return a - b` should be `return a + b`.
