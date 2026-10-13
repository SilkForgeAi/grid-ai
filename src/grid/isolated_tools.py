"""SDK adapters: restricted sessions expose only container-backed tools."""

from openhands.sdk.tool import ToolExecutor, register_tool
from openhands.tools.file_editor.definition import FileEditorAction, FileEditorObservation, FileEditorTool
from openhands.tools.terminal.definition import TerminalAction, TerminalObservation, TerminalTool

from grid.isolation import run_isolated


class IsolatedTerminalExecutor(ToolExecutor):
    def __init__(self, workspace):
        self.workspace = workspace

    def __call__(self, action: TerminalAction, conversation=None):
        if action.is_input or action.reset or not action.command:
            return TerminalObservation.from_text(
                "Isolated commands are stateless; run a complete command.",
                command=action.command,
                exit_code=1,
                is_error=True,
            )
        code, output = run_isolated(
            {"kind": "terminal", "command": action.command}, self.workspace, timeout=min(action.timeout or 120, 300)
        )
        return TerminalObservation.from_text(output, command=action.command, exit_code=code, is_error=code != 0)


class IsolatedEditorExecutor(ToolExecutor):
    def __init__(self, workspace):
        self.workspace = workspace

    def __call__(self, action: FileEditorAction, conversation=None):
        code, output = run_isolated({"kind": "editor", **action.model_dump()}, self.workspace)
        return FileEditorObservation.from_text(output, command=action.command, path=action.path, is_error=code != 0)


class IsolatedTerminalTool(TerminalTool):
    @classmethod
    def create(cls, conv_state, **params):
        return TerminalTool.create(conv_state, executor=IsolatedTerminalExecutor(conv_state.workspace.working_dir))


class IsolatedEditorTool(FileEditorTool):
    @classmethod
    def create(cls, conv_state, **params):
        return [
            FileEditorTool(
                action_type=FileEditorAction,
                observation_type=FileEditorObservation,
                description="View, create, str_replace or insert files inside the isolated project only.",
                executor=IsolatedEditorExecutor(conv_state.workspace.working_dir),
            )
        ]


register_tool("grid_isolated_terminal", IsolatedTerminalTool)
register_tool("grid_isolated_editor", IsolatedEditorTool)
