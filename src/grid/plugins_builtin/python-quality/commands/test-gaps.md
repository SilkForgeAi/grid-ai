---
description: Find code paths without tests and add tests for them
argument-hint: "[file or package]"
---
Find behavior in $ARGUMENTS (or the whole project if empty) that no test covers. List the gaps you found, most important first. Then write focused pytest tests for the top three, run them, and fix any test that fails because the test was wrong - if a test fails because the code is wrong, report it instead of changing the code.
