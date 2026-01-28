from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Self, Any, Iterable, TypeVar, Sequence

import curses
import curses.ascii
import itertools

from prog_signal import UserQuit
from data import (
        Class, Category, LanguagesKey, PracticeSession, make_language_dictionary,
        get_random_word, MINIMUM_STREAK_DISPLAY, congratulation, comiseration
        )

T = TypeVar('T')

TUI_KEY_DOWN      = (curses.KEY_DOWN,)
TUI_KEY_UP        = (curses.KEY_UP,)
TUI_KEY_ENTER     = (
        (curses.KEY_ENTER,),
        (curses.ascii.NL,),
        (curses.ascii.CR,)
        )
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
        recommended to return True from teh callback to prevent unexpected UI
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

    # TODO implement cursor tracking
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
    def draw(self, tui: TuiContext) -> None:
        ...

    @abstractmethod
    def create_bindings(self, tui: TuiContext) -> None:
        ...

    @abstractmethod
    def destroy(self, tui: TuiContext) -> None:
        ...

class CategorySelectionScreen(ScreenBase):
    '''Form for selecting cateogries from classes'''

    def __init__(self, classes: list[Class]):
        self.classes = classes
        self.title_str = "The following classes are available:"
        self.menus: list[CheckboxMenu] = []

        for index, class_ in enumerate(classes):
            class_id = index + 1
            menu = CheckboxMenu(title=f"{class_id}. {class_.name}")
            self.menus.append(menu)
            for cat_index, category in enumerate(class_.categories):
                cat_id = cat_index + 1
                menu.add_entry(f"{class_id}.{cat_id} {category.name}", enabled=True)

        self.cur_menu_idx = 0
        self.cur_entry_idx = 0

    def draw(self, tui: TuiContext):
        '''Form draw calls'''
        tui.clear_screen()
        tui.begin_draw()
        self.layout = Layout(centered_x=True, centered_y=True, padding=1, min_width=50)
        self.layout.add_to_tui(tui)
        self.layout.add_text(self.title_str)

        for menu in self.menus:
            menu.add_to_layout(self.layout)

        tui.end_draw()
        tui.refresh_screen()

        start_x, start_y = self.menus[0].entries[0].rendered_cursor_pos
        tui.move_cursor(start_x, start_y)

    def create_bindings(self, tui: TuiContext) -> None:
        '''Create form bindings'''
        self.accel_map = AcceleratorMap()
        self.accel_map.add_to_tui(tui)
        self.accel_map.map_key(TUI_KEY_DOWN, self.on_down)
        self.accel_map.map_key(TUI_KEY_UP, self.on_up)
        self.accel_map.map_key(as_key(' '), self.on_space)
        self.accel_map.map_keys(TUI_KEY_ENTER, self.on_enter)
        self.accel_map.map_key(as_key('q'), on_quit)

    def destroy(self, tui: TuiContext) -> None:
        '''Destroy UI widgets and bindings and set final result'''
        self.categories: list[Category] = []
        for menu_index, menu in enumerate(self.menus):
            for entry_index, entry in enumerate(menu.entries):
                if entry.enabled:
                    self.categories.append(self.classes[menu_index].categories[entry_index])

        self.accel_map.remove_from_tui(tui)

    def get_next_selection(self, menu_index: int, entry_index: int) -> tuple[int, int]:
        '''Get the indices for the next entry in the form'''
        assert menu_index >= 0 and menu_index < len(self.menus)
        current_menu = self.menus[menu_index]
        n_entries = len(current_menu.entries)
        if menu_index + 1 >= len(self.menus) and entry_index + 1 >= n_entries:
            return (menu_index, entry_index) # no next entry
        if entry_index + 1 >= n_entries:
            return (menu_index + 1, 0) # first entry of next menu
        return (menu_index, entry_index + 1) # next entry

    def get_prev_selection(self, menu_index: int, entry_index: int) -> tuple[int, int]:
        '''Get the indices for the previous entry in the form'''
        assert menu_index >= 0 and menu_index < len(self.menus)
        if menu_index == 0 and entry_index == 0:
            return (menu_index, entry_index) # no previous entry
        if entry_index == 0:
            # last entry of previous menu
            return (menu_index - 1, len(self.menus[menu_index - 1].entries) - 1)
        return (menu_index, entry_index - 1)

    def on_down(self, t: TuiContext):
        self.cur_menu_idx, self.cur_entry_idx = self.get_next_selection(
                self.cur_menu_idx, self.cur_entry_idx)
        x, y = self.menus[self.cur_menu_idx].entries[self.cur_entry_idx].rendered_cursor_pos
        t.move_cursor(x, y)

    def on_up(self, t: TuiContext):
        self.cur_menu_idx, self.cur_entry_idx = self.get_prev_selection(
                self.cur_menu_idx, self.cur_entry_idx)
        x, y = self.menus[self.cur_menu_idx].entries[self.cur_entry_idx].rendered_cursor_pos
        t.move_cursor(x, y)

    def on_enter(self, t: TuiContext):
        t.emit(TUI_OK_EVENT)

    def on_space(self, t: TuiContext):
        entry = self.menus[self.cur_menu_idx].entries[self.cur_entry_idx]
        entry.enabled = not entry.enabled
        t.redraw()
        t.move_cursor(*entry.rendered_cursor_pos)

def select_categories_from_classes_screen(tui: TuiContext, classes: list[Class]) -> list[Category]:
    '''Display TUI screen for selecting categories from classes'''
    # NOTE: this is just first pass code and should be refactored
    title_str = "The following classes are available:"

    tui.add_variable("menus", list())
    menus: list[CheckboxMenu] = tui.get_variable("menus")
    for class_index,class_ in enumerate(classes):
        class_id = class_index + 1
        menu = CheckboxMenu(title=f"{class_id}. {class_.name}")
        menus.append(menu)
        for category_index,category in enumerate(class_.categories):
            category_id = category_index + 1
            # set everything enabled by default
            menu.add_entry(f"{class_id}.{category_id} {category.name}", enabled = True)

    # TODO could use a with block for draw calls
    tui.clear_screen()
    tui.begin_draw()

    layout = Layout(centered_x = True, centered_y = True, padding = 1, min_width = 50)
    layout.add_to_tui(tui)
    layout.add_text(title_str)
    for menu in menus:
        menu.add_to_layout(layout)

    tui.end_draw()
    tui.refresh_screen()

    tui.add_variable("selected_class_index", 0)
    tui.add_variable("selected_category_index", 0)

    def selection_indices(t: TuiContext) -> tuple[int,int]:
        class_index: int | None = t.get_variable("selected_class_index")
        if class_index is None:
            raise RuntimeError("TUI variable missing: class_index")
        category_index: int | None = t.get_variable("selected_category_index")
        if category_index is None:
            raise RuntimeError("TUI variable missing: class_index")
        return (class_index,category_index)

    def set_selection(t: TuiContext, selection: tuple[int,int]):
        class_index, category_index = selection
        t.set_variable("selected_class_index", class_index)
        t.set_variable("selected_category_index", category_index)

    def menu_selection_next(menus: list[CheckboxMenu], selection: tuple[int,int]) -> tuple[int,int]:
        menu_idx,entry_idx = selection
        if menu_idx < 0 or menu_idx >= len(menus):
            raise RuntimeError(f"Invalid menu selection state: {menu_idx}")

        current_menu = menus[menu_idx]
        n_entries = len(current_menu.entries)
        if menu_idx + 1 >= len(menus) and entry_idx + 1 >= n_entries:
            return (menu_idx, entry_idx)
        elif entry_idx + 1 >= n_entries:
            return (menu_idx + 1, 0)
        else:
            return (menu_idx, entry_idx + 1)

    def menu_selection_prev(menus: list[CheckboxMenu], selection: tuple[int,int]) -> tuple[int,int]:
        menu_idx,entry_idx = selection
        if menu_idx < 0 or menu_idx >= len(menus):
            raise RuntimeError(f"Invalid menu selection state: {menu_idx}")

        if menu_idx == 0 and entry_idx == 0:
            return (menu_idx, entry_idx)
        elif entry_idx  == 0:
            new_menu_idx = menu_idx - 1
            return (new_menu_idx, len(menus[new_menu_idx].entries) - 1)
        else:
            return (menu_idx, entry_idx - 1)

    def on_down(t: TuiContext):
        menus: list[CheckboxMenu] = t.get_variable("menus")
        menu_idx,entry_idx = menu_selection_next(menus, selection_indices(t))
        set_selection(t, (menu_idx, entry_idx))
        x,y = menus[menu_idx].entries[entry_idx].rendered_cursor_pos
        t.move_cursor(x, y)

    def on_up(t: TuiContext):
        menus: list[CheckboxMenu] = t.get_variable("menus")
        menu_idx,entry_idx = menu_selection_prev(menus, selection_indices(t))
        set_selection(t, (menu_idx, entry_idx))
        x,y = menus[menu_idx].entries[entry_idx].rendered_cursor_pos
        t.move_cursor(x, y)

    def on_enter(t: TuiContext):
        t.pause()

    def on_space(t: TuiContext):
        menus: list[CheckboxMenu] = t.get_variable("menus")
        menu_idx, entry_idx = selection_indices(t)
        selected_entry = menus[menu_idx].entries[entry_idx]
        selected_entry.enabled = not selected_entry.enabled

        t.redraw()
        t.move_cursor(*selected_entry.rendered_cursor_pos)

    accel_map = AcceleratorMap()
    accel_map.add_to_tui(tui)
    accel_map.map_key(TUI_KEY_DOWN, on_down)
    accel_map.map_key(TUI_KEY_UP, on_up)
    accel_map.map_key(as_key(' '), on_space)
    accel_map.map_keys(TUI_KEY_ENTER, on_enter)
    accel_map.map_key(as_key('q'), on_quit)

    start_x, start_y = menus[0].entries[0].rendered_cursor_pos
    tui.move_cursor(start_x, start_y)

    tui.mainloop()

    # filter classes and categories by menu entry
    categories: list[Category] = []
    for menu_index,menu in enumerate(menus):
        if not isinstance(menu, CheckboxMenu):
            continue

        for entry_index,entry in enumerate(menu.entries):
            if entry.enabled:
                categories.append(classes[menu_index].categories[entry_index])

    tui.destroy_variable("menus")
    tui.destroy_variable("selected_class_index")
    tui.destroy_variable("selected_category_index")
    accel_map.remove_from_tui(tui)
    return categories

def display_selection_menu(
        tui: TuiContext,
        items: Sequence[T],
        title: str,
        *,
        item_display_fn: Callable[[T], str] = str,
        start_index: int = 0
        ) -> T:
    '''Display generic selection menu for selecting an item from a list'''
    # NOTE: this is just first pass code and should be refactored
    if start_index >= len(items): raise ValueError(f"Index out of bounds: {start_index}")
    tui.add_variable("menu", Menu(title=title))
    menu: Menu = tui.get_variable("menu")
    for item in items:
        menu.add_entry(item_display_fn(item))

    tui.clear_screen()
    tui.begin_draw()
    layout = Layout(centered_x = True, centered_y = True, padding = 1, min_width = 50)
    layout.add_to_tui(tui)
    menu.add_to_layout(layout)
    tui.end_draw()
    tui.refresh_screen()

    menu.selected_index = start_index

    def menu_get_bounded_selection(menu: Menu, index: int) -> int:
        index = max(0, index)
        index = min(len(menu.entries) - 1, index)
        return index

    def on_down(t: TuiContext):
        menu: Menu = t.get_variable("menu")
        index = menu_get_bounded_selection(menu, menu.selected_index + 1)
        t.move_cursor(*menu.entries[index].rendered_cursor_pos)
        menu.selected_index = index

    def on_up(t: TuiContext):
        menu: Menu = t.get_variable("menu")
        index = menu_get_bounded_selection(menu, menu.selected_index - 1)
        t.move_cursor(*menu.entries[index].rendered_cursor_pos)
        menu.selected_index = index

    def on_enter(t: TuiContext):
        t.pause()

    accel_map = AcceleratorMap()
    accel_map.add_to_tui(tui)
    accel_map.map_key(TUI_KEY_DOWN, on_down)
    accel_map.map_key(TUI_KEY_UP, on_up)
    accel_map.map_keys(TUI_KEY_ENTER, on_enter)
    accel_map.map_key(as_key('q'), on_quit)

    tui.move_cursor(*menu.entries[menu.selected_index].rendered_cursor_pos)
    tui.mainloop()

    choice = menu.selected_index

    tui.destroy_variable("menu")
    accel_map.remove_from_tui(tui)
    return items[choice]

def select_language_screen(
        tui: TuiContext,
        languages_keys: list[LanguagesKey]
        ) -> LanguagesKey:
    '''Display menu for selecting languages from list'''
    # NOTE: this is just first pass code and should be refactored
    if len(languages_keys) == 1:
        # TODO: notify the user?
        return languages_keys[0]

    def display_languages_key(key: LanguagesKey) -> str:
        return f"{key[1]} -> {key[0]}"

    menu_title = "Select a language pair:"
    return display_selection_menu(tui, languages_keys, menu_title,
                                  item_display_fn = display_languages_key)

def configure_session_tui(tui: TuiContext, classes: list[Class]) -> PracticeSession:
    '''Configure the practice session with TUI controls'''
    # NOTE: this is just first pass code and should be refactored

    # ScreenFlow
    # TODO work on how data is piped between screens

    def dummy_pause(t: TuiContext, _) -> bool:
        t.pause()
        return True

    tui.add_callback(TUI_OK_EVENT, dummy_pause)

    # program state TUI_BEGIN_STATE
    first_screen = CategorySelectionScreen(classes)
    first_screen.create_bindings(tui)
    first_screen.draw(tui)
    tui.mainloop()
    first_screen.destroy(tui)

    categories = first_screen.categories

    #categories = select_categories_from_classes_screen(tui, classes)
    dictionary = make_language_dictionary(categories)
    if len(dictionary.keys()) == 0:
        # TODO: handle empty dictionary
        raise NotImplementedError

    languages = select_language_screen(tui, list(dictionary.keys()))
    return PracticeSession(categories, languages, dictionary[languages])

def ask_rounds_tui(tui: TuiContext) -> int:
    '''Ask user how many rounds they want to play'''
    selection = (5, 10, 20, 50)
    menu_title = "How many rounds?"
    display = lambda n: f"{n} rounds"
    return display_selection_menu(
            tui, selection, menu_title, item_display_fn=display, start_index=1)

def play_memorize_round_tui(tui: TuiContext, session: PracticeSession) -> None:
    '''Play round of Memorize in TUI mode'''
    # NOTE: this is just first pass code and should be refactored
    word = get_random_word(session)
    answers = session.dictionary[word]
    session.total_tests += 1

    # define screen states
    GUESSING           = 0
    WAITING_TO_RETRY   = 1
    WORD_GUESSED       = 2
    WORD_MISSED        = 3

    # initialise tui variables
    tui.add_variable("guesses_left", 3)
    guesses_left: int | None = tui.get_variable("guesses_left")
    if guesses_left is None:
        raise RuntimeError("Variable could not be set: guesses_left")

    display_guesses = lambda g: f"{g} guesses" if g > 1 \
            else "1 guess" if g == 1 \
            else "no guesses"

    # Technically this behaves differently than the old terminal mode
    # but this is actually the behaviour I intended
    display_title = lambda session: \
            f"Test #{session.total_tests}" \
            if session.streak < MINIMUM_STREAK_DISPLAY \
            else f"Test #{session.total_tests} | Streak: {session.streak}"

    tui.add_variable("title", display_title(session))
    tui.add_variable("answer_prompt", f"Answer ({display_guesses(guesses_left)} left):")
    tui.add_variable("answer_response", "")
    tui.add_variable("feedback_1", "")
    tui.add_variable("feedback_2", "")
    tui.add_variable("state", GUESSING)

    # draw calls
    tui.clear_screen()
    tui.begin_draw()

    layout = Layout(centered_x=True, centered_y=True, min_width = 50)
    layout.add_to_tui(tui)
    layout.add_evaluated_text(lambda: tui.get_variable("title"))
    layout.add_text("")
    layout.add_text("Your word is:")
    layout.add_text(word)
    layout.add_text("")
    layout.add_evaluated_text(lambda: tui.get_variable("answer_prompt"))

    response_render_target = layout.add_evaluated_text(
            lambda: tui.get_variable("answer_response"))
    tui.add_variable("entry", response_render_target)

    layout.add_text("")
    layout.add_evaluated_text(lambda: tui.get_variable("feedback_1"))
    layout.add_evaluated_text(lambda: tui.get_variable("feedback_2"))

    tui.end_draw()
    tui.refresh_screen()

    # set initial state
    cursor_x = response_render_target.start_x
    cursor_y = response_render_target.start_y
    tui.move_cursor(cursor_x, cursor_y)

    # event handling
    def move_cursor_to_entry(t: TuiContext):
        response: str = t.get_variable("answer_response")
        entry: RenderTarget = t.get_variable("entry")
        t.move_cursor(x=entry.start_x + len(response), y=entry.start_y)

    def on_entry_key_press(t: TuiContext, k: TuiKey) -> bool:
        state: int = t.get_variable("state")
        if state != GUESSING:
            return True

        key_str = key_to_str(k)
        current_response: str = t.get_variable("answer_response")
        if k == TUI_KEY_BACKSPACE and len(current_response) == 0:
            pass
        elif k == TUI_KEY_BACKSPACE:
            t.clear_screen() # anticipate needing to redraw
            t.set_variable("answer_response", current_response[:-1])
            t.emit("text_changed")
        elif len(key_str) > 1: # key is special key
            pass
        else:
            t.set_variable("answer_response", current_response + key_str)
            t.emit("text_changed")
        return True

    def on_text_changed(t: TuiContext, _) -> bool:
        t.redraw()
        move_cursor_to_entry(t)
        return True

    def on_enter(t: TuiContext):
        response: str = t.get_variable("answer_response")
        if len(response) == 0 : return

        state: int = t.get_variable("state")
        if state == GUESSING:            t.emit("submit")
        elif state == WAITING_TO_RETRY:  t.emit("retry")
        elif state == WORD_GUESSED:      t.emit("finish")
        elif state == WORD_MISSED:       t.emit("finish")
        else: raise RuntimeError(f"Unknown state in play_memorize_round_tui: {state}")

    def correct(t: TuiContext, response: str):
        session.streak += 1
        t.set_variable("feedback_1", f"{congratulation()}")
        if len(answers) > 1:
            other_answers = (answer for answer in answers if answer != response)
            t.set_variable(
                    "feedback_2",
                    f"Other answers could have been {' or '.join(other_answers)}")

        t.set_variable("state", WORD_GUESSED)
        t.redraw()
        move_cursor_to_entry(t)

    def wrong(t: TuiContext, _):
        old_streak = session.streak
        session.streak = 0
        if old_streak >= MINIMUM_STREAK_DISPLAY:
            t.set_variable("title", f"{display_title(session)} | Streak of {old_streak} lost...")

        guesses_left: int | None = t.get_variable("guesses_left")
        if guesses_left is None:
            raise RuntimeError("Variable missing: guesses_left")

        guesses_left -= 1
        if guesses_left == 0:
            t.set_variable("answer_prompt", f"Answer ({display_guesses(guesses_left)} left):")
            t.set_variable("feedback_1", f"{comiseration()}")
            t.set_variable(
                    "feedback_2",
                    f"The correct answer was {answers[0]}"
                    if len(answers) == 1
                    else f"The correct answers were {' or '.join(answers)}")
            t.set_variable("state", WORD_MISSED)
            t.redraw()
            move_cursor_to_entry(t)

        else:
            t.set_variable("answer_prompt", f"Answer ({display_guesses(guesses_left)} left):")
            t.set_variable("feedback_1", "Incorrect")
            t.set_variable("feedback_2", "Prese Enter to retry...")
            t.set_variable("guesses_left", guesses_left)
            t.redraw()
            move_cursor_to_entry(t)

            t.set_variable("state", WAITING_TO_RETRY)

    def on_submit(t: TuiContext, _) -> bool:
        response: str = t.get_variable("answer_response")
        if response.lower().strip() in answers: correct(t, response)
        else: wrong(t, response)
        return True

    def on_retry(t: TuiContext, _) -> bool:
        guesses_left: int = t.get_variable("guesses_left")
        t.set_variable("answer_prompt", f"Answer ({display_guesses(guesses_left)} left):")
        t.set_variable("answer_response", "")
        t.set_variable("feedback_1", "")
        t.set_variable("feedback_2", "")
        t.set_variable("state", GUESSING)
        t.clear_screen()
        t.redraw()
        move_cursor_to_entry(t)
        return True

    def on_finish(t: TuiContext, _) -> bool:
        state: int = t.get_variable("state")
        if state == WORD_MISSED and word not in session.missed_words:
            session.missed_words.append(word)

        t.pause()
        return True

    tui.add_callback(TUI_KEY_EVENT, on_entry_key_press)
    tui.add_callback("text_changed", on_text_changed)
    tui.add_callback("submit", on_submit)
    tui.add_callback("retry", on_retry)
    tui.add_callback("finish", on_finish)

    accel_map = AcceleratorMap()
    accel_map.add_to_tui(tui)
    accel_map.map_keys(TUI_KEY_ENTER, on_enter)

    tui.mainloop()

    # cleanup
    tui.destroy_variable("guesses_left")
    tui.destroy_variable("title")
    tui.destroy_variable("answer_prompt")
    tui.destroy_variable("answer_response")
    tui.destroy_variable("feedback_1")
    tui.destroy_variable("feedback_2")
    tui.destroy_variable("state")
    tui.destroy_variable("entry")
    tui.remove_callback(TUI_KEY_EVENT, on_entry_key_press)
    tui.remove_callback("text_changed", on_text_changed)
    tui.remove_callback("submit", on_submit)
    tui.remove_callback("retry", on_retry)
    tui.remove_callback("finish", on_finish)
    accel_map.remove_from_tui(tui)

def ask_more_rounds_tui(tui: TuiContext) -> int:
    '''Ask user if they want more rounds'''
    selection = (0, 5, 10, 20, 50)
    menu_title = "How many rounds?"
    display = lambda n: f"{n} rounds" if n != 0 else "Finish"
    return display_selection_menu(tui, selection, menu_title, item_display_fn=display)

def play_memorize_game_tui(tui: TuiContext, session: PracticeSession) -> None:
    '''Play Memorize game in TUI mode'''
    rounds_left = ask_rounds_tui(tui)
    while rounds_left > 0:
        play_memorize_round_tui(tui, session)
        rounds_left -= 1

        if rounds_left == 0:
            rounds_left = ask_more_rounds_tui(tui)

def display_summary_screen(tui: TuiContext, session: PracticeSession) -> None:
    '''Display results of practice session'''
    # draw calls
    tui.clear_screen()
    tui.begin_draw()

    layout = Layout(centered_x=True, centered_y=True, min_width=50)
    layout.add_to_tui(tui)
    layout.add_text(f"Total test: {session.total_tests}")
    if len(session.missed_words) == 0:
        layout.add_text("There were no missed words")
    else:
        layout.add_text("Missed words:")
        for word in session.missed_words:
            layout.add_text(f"    {word}")

    layout.add_text("")
    layout.add_text("Press any key to quit...")

    tui.end_draw()
    tui.refresh_screen()

    # event handling
    def on_key_press(t: TuiContext, _):
        t.pause()
        return True

    tui.add_callback(TUI_KEY_EVENT, on_key_press)
    tui.mainloop()

    # cleanup
    tui.remove_callback(TUI_KEY_EVENT, on_key_press)

def main_tui_mode(stdscr: curses.window, classes: list[Class]) -> None:
    tui = TuiContext(stdscr)
    accel_map = AcceleratorMap(key_map={
        as_ctrl_key('c'): on_quit })
    accel_map.add_to_tui(tui)

    session = configure_session_tui(tui, classes)
    play_memorize_game_tui(tui, session)
    display_summary_screen(tui, session)

    accel_map.remove_from_tui(tui)

def run_main_tui_mode(classes: list[Class]) -> None:
    '''Run tui mode'''
    curses.wrapper(main_tui_mode, classes)

