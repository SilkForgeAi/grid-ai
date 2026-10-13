from grid.events import action_info, describe_action, is_action, is_observation, observation_text


class T:
    def __init__(self, text):
        self.text = text


class Obs:
    def __init__(self, content):
        self.content = content


class ObsEvent:
    def __init__(self, content, tool="terminal"):
        self.observation = Obs(content)
        self.action_id = "a1"
        self.tool_name = tool


class Act:
    command = "pytest -q"


class ActEvent:
    tool_call_id = "c1"
    thought = [T("hi")]
    tool_name = "terminal"
    action = Act()


def test_observation_text_flattens_textcontent_lists():
    e = ObsEvent([T("===== 1 failed, 5 passed in 0.4s =====")])
    assert "5 passed" in observation_text(e)


def test_non_observation_has_no_text():
    class Msg:
        content = "12 passed"
    assert observation_text(Msg()) == ""


def test_action_helpers():
    e = ActEvent()
    assert is_action(e) and not is_observation(e)
    assert action_info(e).command == "pytest -q"
    assert describe_action(e) == "$ pytest -q"
