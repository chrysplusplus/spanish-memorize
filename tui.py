from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Self, Any, Iterable, TypeVar, Sequence

import curses
import curses.ascii
import itertools

from prog_signal import UserQuit
T = TypeVar('T')

TUI_KEY_DOWN      = (curses.KEY_DOWN,)
TUI_KEY_UP        = (curses.KEY_UP,)
TUI_KEY_ENTER     = ((curses.KEY_ENTER,),
                     (curses.ascii.NL,),
                     (curses.ascii.CR,))
TUI_KEY_BACKSPACE = (curses.KEY_BACKSPACE,)

TUI_KEY_EVENT = ""
TUI_OK_EVENT = "ok"

TuiKey = tuple[int, ...]

def validate_keystr(key_str: str) -> str:
    '''Trim and validate key representation

    Raise ValueError if key representation is invalid'''
    key_str = key_str.lower()
    if len(key_str) == 0 or not key_str.isprintable():
        raise ValueError(f"Invalid key character: {key_str}")
    return key_str[0]

def as_key(key_str: str) -> TuiKey:
    '''Convert string representing keyboard character to key code

    Raise ValueError if key representation is invalid'''
    return (ord(validate_keystr(key_str)),)

def as_ctrl_key(key_str: str) -> TuiKey:
    '''Convert string to control key code

    For example: as_ctrl_key('c') would yield the key code for Ctrl-C

    Raise ValueError if key representation is invalid'''
    return (curses.ascii.ctrl(ord(validate_keystr(key_str))),)

def key_to_str(key: TuiKey) -> str:
    '''Convert TuiKey to printable string'''
    if len(key) == 1:
        return curses.keyname(key[0]).decode("utf-8")
    else:
        return bytes(key).decode("utf-8")

class TuiVariableResultErr(Enum):
    Ok = auto()
    VariableDoesExist = auto()
    TypeMismatch = auto()

@dataclass
class TuiVariableResult:
    error: TuiVariableResultErr
    type_: type
    value: Any

class TuiContext:
    def __init__(self, stdscr: curses.window):
        self.stdscr = stdscr
        self.is_running: bool = False
        self.draw_stack: list[Callable[[TuiContext], None]] = []
        self.variables: dict[str, Any] = {}
        self.callbacks: dict[str, list[Callable[[Self, TuiKey], bool]]] = {}
        self.event_queue: list[str] = []

        self._initialise_tui()

    def _initialise_tui(self):
        '''Internal function for setting up curses'''
        # set raw mode
        curses.raw()

        # set nodelay mode
        self.stdscr.nodelay(True)

        # use default colours
        curses.use_default_colors()

        # clear and refresh on initialisation
        self.stdscr.clear()
        self.stdscr.refresh()

        # define application colours NOTE: hardcoded for now
        # NOTE currently disabled
        #curses.start_color()
        #curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
        #curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)
        #curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_WHITE)

    @property
    def screen_size(self) -> tuple[int, int]:
        '''Get maxy,maxx for the TUI'''
        return self.stdscr.getmaxyx()

    def add_variable(self, name: str, initial_value: Any) -> bool:
        '''Create a TUI variable; Return False if variable already exists'''
        if self.variables.get(name, None) is not None: return False
        self.variables[name] = initial_value
        return True

    # TODO wrap return with TuiVariableResult
    def get_variable(self, name: str) -> Any:
        '''Return value of TUI variable; or None if variable is unknown'''
        return self.variables.get(name, None)

    def set_variable(self, name: str, value: Any) -> TuiVariableResultErr:
        '''Set the value of a TUI variable; Return success state'''
        if name not in self.variables.keys():
            return TuiVariableResultErr.VariableDoesExist

        cur_val = self.variables[name]
        if type(cur_val) != type(value):
            return TuiVariableResultErr.TypeMismatch

        self.variables[name] = value
        return TuiVariableResultErr.Ok

    def destroy_variable(self, name: str):
        '''Remove TUI variable'''
        if name in self.variables.keys():
            del self.variables[name]

    def add_callback(self, event_type: str, callback: Callable[[Self, TuiKey], bool]) -> bool:
        '''Add callback for handling the specified event type

        If succcessful, callback is added at the top of the stack and so will be
        called before the previous items in the stack during the event callback
        stage

        callback should be a callable that accepts a TuiContext and a TuiKey as its
        parameters, which represent the current TUI context and the key input that
        triggered the current event respectively, and returns a bool, which if True
        indicates that the next event callback should be used. It is generally
        recommended to return True from the callback to prevent unexpected UI
        behaviour.

        Return False if callback was previously added for this event type'''

        callback_stack = self.callbacks.get(event_type, None)
        if callback_stack is None:
            callback_stack = [ callback ]
            self.callbacks[event_type] = callback_stack
            return True

        if callback in callback_stack:
            return False

        callback_stack.insert(0, callback)
        return True

    def remove_callback(self, event_type: str, callback: Callable[[Self, TuiKey], bool]):
        '''Remove registered callback handler'''
        callback_stack = self.callbacks.get(event_type, None)
        if callback_stack is None:
            return
        if callback in callback_stack:
            callback_stack.remove(callback)

    def begin_draw(self):
        '''Prepare TUI context for drawing the next screen state'''
        self.draw_stack.clear()

    def end_draw(self):
        '''Call stored drawing callbacks'''
        for draw_call in self.draw_stack:
            draw_call(self)

    def redraw(self):
        '''Redraw the screen using the previous drawing callbacks'''
        self.end_draw()

    def clear_screen(self):
        '''Clear the TUI'''
        self.stdscr.clear()

    def refresh_screen(self):
        '''Refresh the TUI'''
        self.stdscr.refresh()

    def draw_text(self, text: str, x: int, y: int):
        '''Draw text starting at position on screen'''
        self.stdscr.addstr(y, x, text)

    def move_cursor(self, x: int, y: int):
        '''Move cursor to position'''
        maxy, maxx = self.stdscr.getmaxyx()
        if x >= 0 and x <= maxx and y >= 0 and y <= maxy:
            self.stdscr.move(y, x)

    def _process_event_callback(self, key: TuiKey, stack: list[Callable[[Self, TuiKey], bool]]):
        '''Process event callback'''
        for callback in stack:
            do_next = callback(self, key)
            if not do_next:
                break

    def _process_event_queue(self, key: TuiKey):
        '''Process event queue'''
        while len(self.event_queue) != 0:
            event_type = self.event_queue.pop(0)
            callback_stack = self.callbacks.get(event_type, None)
            if callback_stack is None:
                continue

            self._process_event_callback(key, callback_stack)

    def _get_key(self) -> TuiKey:
        '''Get key from typeahead'''
        key_bytes: list[int] = []
        key = self.stdscr.getch()
        while key != -1:
            key_bytes.append(key)
            key = self.stdscr.getch()

        return tuple(key_bytes)

    def mainloop(self):
        '''Run mainloop for handling user input'''
        self.is_running = True
        while self.is_running:
            key = self._get_key()
            if len(key) != 0:
                self.event_queue.append(TUI_KEY_EVENT)

            self._process_event_queue(key)

    def pause(self):
        '''Return control back to program code'''
        self.is_running = False

    def emit(self, event_type: str):
        self.event_queue.append(event_type)

AcceleratorHandle = Callable[[TuiContext], None]

class AcceleratorMap:
    def __init__(self,
                 *,
                 key_map: dict[TuiKey, AcceleratorHandle] | None = None):
        self.key_map: dict[TuiKey, Callable[[TuiContext], None]] = {}
        if key_map is not None:
            self.key_map = { **self.key_map, **key_map }

    def on_key_press(self, t: TuiContext, key: TuiKey) -> bool:
        callback = self.key_map.get(key, None)
        if callback is not None:
            callback(t)
            return False    # prevent further propagation that might be unexpected

        return True

    def add_to_tui(self, tui: TuiContext):
        '''Add to event loop'''
        tui.add_callback(TUI_KEY_EVENT, self.on_key_press)

    def remove_from_tui(self, tui: TuiContext):
        '''Remove from event loop'''
        tui.remove_callback(TUI_KEY_EVENT, self.on_key_press)

    def map_key(self, key: TuiKey, callback: Callable[[TuiContext], None]) -> bool:
        '''Map a key to a callback; Return False if mapping already exists'''
        if key in self.key_map.keys():
            return False

        self.key_map[key] = callback
        return True

    def map_keys(self, keys: Iterable[TuiKey],
                 callback: Callable[[TuiContext], None]
                 ) -> bool:
        '''Attempt to map all provided keys to a callback. Return False if any
        mapping fails and do not set any of the mappings'''
        if any(key in self.key_map.keys() for key in keys):
            return False

        for key in keys:
            self.key_map[key] = callback

        return True

POST_DO_NOTHING = lambda _,__: None

@dataclass
class RenderTarget:
    text_render_fn: Callable[[], Iterable[str]]
    post_render_fn: Callable[[int, int], None] = POST_DO_NOTHING
    start_x: int = -1
    start_y: int = -1

class Layout:
    def __init__(
            self, *,
            centered_x: bool = False,
            centered_y: bool = False,
            padding: int = 0,
            min_width: int = -1,
            min_height: int = -1):

        self.centered_x = centered_x
        self.centered_y = centered_y
        self.padding = padding
        self.min_width = min_width
        self.min_height = min_height

        self.offset_x: int = 0
        self.offset_y: int = 0
        self.items: list[RenderTarget] = []

    def add_to_tui(self, tui: TuiContext):
        '''Add to Tui'''
        tui.draw_stack.append(self.on_draw)

    def on_draw(self, t: TuiContext):
        lines: list[str] = []
        max_width: int = 0

        for index, item in enumerate(self.items):
            if index != 0 and self._padding != 0:
                lines.extend(itertools.repeat("", self._padding))

            item.start_y = len(lines)
            text = item.text_render_fn()
            width = max(len(line) for line in text)
            max_width = max(width, max_width)
            lines.extend(text)

        width = max(self._min_width, max_width)
        height = max(self._min_height, len(lines))
        screen_height, screen_width = t.screen_size
        width = min(width, screen_width)
        height = min(height, screen_height)

        start_y: int
        if self._centered_y:
            start_y = (screen_height - height) // 2
        else:
            start_y = 0

        start_x: int
        if self._centered_x:
            start_x = (screen_width - width) // 2
        else:
            start_x = 0

        for index, line in enumerate(lines[:height]):
            t.draw_text(line[:width], start_x, start_y + index)

        for item in self.items:
            item.start_y += start_y
            item.start_x = start_x
            item.post_render_fn(item.start_x, item.start_y)

    @property
    def centered_x(self) -> bool:
        return self._centered_x

    @centered_x.setter
    def centered_x(self, value: bool):
        self._centered_x = value

    @property
    def centered_y(self) -> bool:
        return self._centered_y

    @centered_y.setter
    def centered_y(self, value: bool):
        self._centered_y = value

    @property
    def padding(self) -> int:
        return self._padding

    @padding.setter
    def padding(self, value: int):
        if value < 0:
            raise ValueError(f"Layout padding must be >= 0: {value}")
        self._padding = value

    @property
    def min_width(self) -> int:
        return self._min_width

    @min_width.setter
    def min_width(self, value: int):
        self._min_width = value

    @property
    def min_height(self) -> int:
        return self._min_height

    @min_height.setter
    def min_height(self, value: int):
        self._min_height = value

    def add_text(self, text: str) -> RenderTarget:
        '''Add text to layout renderer'''
        target = RenderTarget(lambda: (text, ))
        self.items.append(target)
        return target

    def add_evaluated_text(self, eval_fn: Callable[[], str]) -> RenderTarget:
        '''Add text which is evaluated at draw time'''
        target = RenderTarget(lambda: (eval_fn(), ))
        self.items.append(target)
        return target

    def add_render_target(self, target: RenderTarget):
        self.items.append(target)

@dataclass
class CheckboxMenuEntry:
    text: str
    enabled: bool = field(default = False, kw_only = True)
    rendered_cursor_pos: tuple[int,int] = (-1, -1)

class CheckboxMenu:
    def __init__(self, *, title: str | None = None):
        self.title = title
        self.entries: list[CheckboxMenuEntry] = []

        self.initialise_target()

    def initialise_target(self):
        self.button_cursor_pairs: list[tuple[CheckboxMenuEntry, tuple[int, int]]] = []
        self.lines: list[str] = []
        self.target = RenderTarget(
                text_render_fn=self.on_render,
                post_render_fn=self.on_post_render)

    def add_to_layout(self, layout: Layout):
        '''Add checkbox menu to layout renderer'''
        layout.add_render_target(self.target)

    def add_entry(self, text: str, *, enabled: bool = True) -> CheckboxMenuEntry:
        '''Add entry to checkbox menu'''
        entry = CheckboxMenuEntry(text, enabled=enabled)
        self.entries.append(entry)
        return entry

    def on_render(self) -> list[str]:
        self.button_cursor_pairs.clear()
        self.lines.clear()

        if self.title is not None:
            self.lines.append(self.title)

        for index, entry in enumerate(self.entries):
            button = "[X]" if entry.enabled else "[ ]"
            self.lines.append(f"{button} {entry.text}")
            self.button_cursor_pairs.append((entry, (1, index + 1)))

        return self.lines

    def on_post_render(self, x: int, y: int):
        for entry, cursor in self.button_cursor_pairs:
            cursor_x, cursor_y = cursor
            entry.rendered_cursor_pos = (x + cursor_x, y + cursor_y)

@dataclass
class MenuEntry:
    text: str
    rendered_cursor_pos: tuple[int,int] = (-1, -1)

class Menu:
    def __init__(self, *, title: str | None = None):
        self.title = title
        self.entries: list[MenuEntry] = []
        self.selected_index: int = -1

        self.initialise_target()

    def initialise_target(self):
        self.button_cursor_pairs: list[tuple[MenuEntry, tuple[int, int]]] = []
        self.target = RenderTarget(
                text_render_fn=self.on_render, post_render_fn=self.on_post_render)

    def add_to_layout(self, layout: Layout):
        '''Add to layout renderer'''
        layout.add_render_target(self.target)

    def add_entry(self, text: str) -> MenuEntry:
        '''Add entry to menu'''
        entry = MenuEntry(text)
        self.entries.append(entry)
        return entry

    def on_render(self) -> list[str]:
        self.button_cursor_pairs.clear()
        lines: list[str] = []

        if self.title is not None:
            lines.append(self.title)

        for index, entry in enumerate(self.entries):
            lines.append(f"  {entry.text}")
            self.button_cursor_pairs.append((entry, (0, index + 1)))

        return lines

    def on_post_render(self, x: int, y: int):
        for entry, cursor in self.button_cursor_pairs:
            cursor_x, cursor_y = cursor
            entry.rendered_cursor_pos = (x + cursor_x, y + cursor_y)

def on_quit(_):
    '''Event handler for quitting the program'''
    raise UserQuit

class ScreenBase(ABC):
    '''Base class for forms. Subclasses must provide full implementation'''
    @abstractmethod
    def __init__(self, prog_data: dict):
        ...

    @abstractmethod
    def draw(self, tui: TuiContext) -> None:
        ...

    @abstractmethod
    def create_bindings(self, tui: TuiContext) -> None:
        ...

    @abstractmethod
    def destroy(self, tui: TuiContext) -> None:
        ...

TUI_BEGIN_STATE = 0
TUI_END_STATE = -1

@dataclass
class TuiProgScreen:
    screen_type: type
    next_state: int

class TuiProgram:
    '''Object representing the combined program state of the TUI and data'''

    def __init__(self, tui: TuiContext, prog_data: dict):
        self.tui = tui
        self.prog_data = prog_data

        self.state: int = TUI_BEGIN_STATE
        self.screen: ScreenBase | None = None
        self.screens: dict[int, TuiProgScreen] = {}

        self.tui.add_callback(TUI_OK_EVENT, self.on_ok)

    def define_screen(self, state: int, screen_class: type, next_state: int):
        '''Define a screen to display when program enters the specified state,
        as well as the next state after an Ok event. The screen type must be a
        subclass of ScreenBase.

        This does not check if another screen was registered for the specified
        state, so take care not to overwrite screens if that is not your intention.

        Raise TypeError if screen_class is not a subclass of ScreenBase'''
        if not issubclass(screen_class, ScreenBase):
            raise TypeError(f"Screen type does not subclass ScreenBase: {screen_class}")

        self.screens[state] = TuiProgScreen(screen_class, next_state)

    def on_ok(self, t: TuiContext, _) -> bool:
        '''On Ok event handler

        Exit when program reaches end state TUI_END_STATE

        Raise RuntimeError if next state is unknown

        Return True'''
        assert self.screen is not None
        self.screen.destroy(t)

        # NOTE this is temporary patch to allow branching state
        # TODO implement event data
        if "next_state_override" in self.prog_data.keys():
            self.state = self.prog_data["next_state_override"]
            del self.prog_data["next_state_override"]
        else:
            assert self.state in self.screens.keys()
            self.state = self.screens[self.state].next_state

        if self.state == TUI_END_STATE:
            self.screen = None
            t.pause()
        elif self.state not in self.screens.keys():
            raise RuntimeError(f"Unknown state after {type(self.screen)}: {self.state}")
        else:
            self.screen = self.screens[self.state].screen_type(self.prog_data)
            assert self.screen is not None
            self.screen.create_bindings(t)
            self.screen.draw(t)

        return True

    def run(self):
        '''Run the program, returning after program enters TUI_END_STATE

        Raise RuntimeError if state is unknown'''
        if self.state not in self.screens.keys():
            raise RuntimeError(f"Unknown state: {self.state}")

        self.screen = self.screens[self.state].screen_type(self.prog_data)
        assert self.screen is not None
        self.screen.create_bindings(self.tui)
        self.screen.draw(self.tui)
        self.tui.mainloop()

class MenuScreen(ScreenBase):
    '''Screen for generic menu'''

    def __init__(self,
                 prog_data: dict,
                 items: Sequence[T],
                 title: str,
                 *,
                 item_display_fn: Callable[[T], str] = str,
                 start_index: int = 0):
        '''Display generic selection menu for selecting an item from a list

        Raise ValueError if start_index is out of bounds'''
        if start_index >= len(items):
            raise ValueError(f"Index out of bounds: {start_index}")

        self.prog_data = prog_data
        self.items = items

        self.menu = Menu(title=title)
        for item in items:
            self.menu.add_entry(item_display_fn(item))

        self.menu.selected_index = start_index

    def draw(self, tui: TuiContext) -> None:
        '''Draw calls to render menu'''
        tui.clear_screen()
        tui.begin_draw()
        self.layout = Layout(centered_x=True, centered_y=True, padding=1, min_width=50)
        self.layout.add_to_tui(tui)
        self.menu.add_to_layout(self.layout)
        tui.end_draw()
        tui.refresh_screen()

        tui.move_cursor(*self.menu.entries[self.menu.selected_index].rendered_cursor_pos)

    def create_bindings(self, tui: TuiContext) -> None:
        '''Create bindings for event handling'''
        self.accel_map = AcceleratorMap()
        self.accel_map.add_to_tui(tui)
        self.accel_map.map_key(TUI_KEY_DOWN, self.on_down)
        self.accel_map.map_key(TUI_KEY_UP, self.on_up)
        self.accel_map.map_keys(TUI_KEY_ENTER, self.on_enter)
        # TODO maybe move so that on_quit can be moved ???
        self.accel_map.map_key(as_key('q'), on_quit)

    def destroy(self, tui: TuiContext) -> None:
        '''Destroy UI widgets and set program data

        Set prog_data["selection"] to be the selected object'''
        self.accel_map.remove_from_tui(tui)
        self.prog_data["selection"] = self.items[self.menu.selected_index]

    def get_bounded_selection_index(self, index: int) -> int:
        '''Return the bounded index in menu entries'''
        index = max(0, index)
        index = min(len(self.menu.entries) - 1, index)
        return index

    def on_down(self, t: TuiContext):
        index = self.get_bounded_selection_index(self.menu.selected_index + 1)
        self.menu.selected_index = index
        t.move_cursor(*self.menu.entries[index].rendered_cursor_pos)

    def on_up(self, t: TuiContext):
        index = self.get_bounded_selection_index(self.menu.selected_index - 1)
        self.menu.selected_index = index
        t.move_cursor(*self.menu.entries[index].rendered_cursor_pos)

    def on_enter(self, t: TuiContext):
        t.emit(TUI_OK_EVENT)

