from grid.teaching import DepthLevel, teaching_prompt, why_did_this_break_prompt


def test_depth_levels_produce_distinct_prompts():
    beginner = teaching_prompt(DepthLevel.BEGINNER)
    pro = teaching_prompt(DepthLevel.PRO)
    assert "BEGINNER" in beginner
    assert "PRO" in pro
    assert beginner != pro


def test_off_is_empty():
    assert teaching_prompt(DepthLevel.OFF) == ""


def test_why_did_this_break_prompt_mentions_root_cause():
    text = why_did_this_break_prompt().lower()
    assert "root cause" in text or "why this broke" in text
