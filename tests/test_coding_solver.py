"""Unit tests for Universal Coding Synthesis, Debugging, and Editor Controller."""

import pytest
from core.ai_solver import AISolver
from core.detector import UniversalDetector


def test_coding_problem_synthesis():
    solver = AISolver()

    title = "Two Sum"
    description = (
        "Given an array of integers nums and an integer target, "
        "return indices of the two numbers such that they add up to target."
    )
    constraints = "2 <= nums.length <= 10^4, -10^9 <= nums[i] <= 10^9"
    sample_cases = "Input: nums = [2,7,11,15], target = 9\nOutput: [0,1]"
    starter_code = "class Solution:\n    def twoSum(self, nums: list[int], target: int) -> list[int]:\n        pass"

    # Test Python generation
    solution = solver.solve_coding_problem(
        title=title,
        description=description,
        constraints=constraints,
        sample_cases=sample_cases,
        starter_code=starter_code,
        language="python",
    )

    assert solution is not None
    assert solution.language == "python"
    assert "twoSum" in solution.code
    assert "return" in solution.code
    assert len(solution.code) > 20


def test_coding_problem_cpp_synthesis():
    solver = AISolver()

    title = "Reverse a String"
    description = "Given a string s, return the reversed string."

    solution = solver.solve_coding_problem(
        title=title,
        description=description,
        language="cpp",
    )

    assert solution is not None
    assert solution.language == "cpp"
    assert ("std::" in solution.code or "string" in solution.code or "#include" in solution.code)


def test_code_self_debugging():
    solver = AISolver()

    problem_desc = "Compute factorial of n. For n=0 return 1."
    buggy_code = "def factorial(n):\n    return n * factorial(n-1)  # Bug: No base case"
    error_logs = "RecursionError: maximum recursion depth exceeded in comparison"
    failed_test = "Input: n = 0\nExpected: 1\nActual: RecursionError"

    fixed = solver.debug_code_solution(
        problem_description=problem_desc,
        current_code=buggy_code,
        error_logs=error_logs,
        failed_test_case=failed_test,
        language="python",
    )

    assert fixed is not None
    # Execute the fixed code and verify factorial functionality
    namespace = {}
    exec(fixed.code, namespace)
    assert "factorial" in namespace
    factorial_fn = namespace["factorial"]
    assert factorial_fn(0) == 1
    assert factorial_fn(1) == 1
    assert factorial_fn(5) == 120
