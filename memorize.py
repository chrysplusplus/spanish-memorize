from argparse import ArgumentParser
from collections import namedtuple
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional, Any, Iterable, Self, TypeVar

import itertools
import json
import random
import re

USE_CURSES: bool
try:
    import curses
    import curses.ascii
    USE_CURSES = True
except ImportError:
    USE_CURSES = False

class CategoryType(Enum):
    Unknown = auto()
    Vocabulary = auto()

@dataclass
class CategoryEntry:
    data: dict[str, str | list[str]]

@dataclass
class Category:
    name: str
    type_: CategoryType
    contents: list[CategoryEntry]

@dataclass
class Class:
    name: str
    categories: list[Category]

# NOTE: languages are structured like in the json file:
#   spanish -> english (many -> one)
# I'm just writing very generic code
@dataclass
class PracticeSession:
    categories: list[Category]
    languages: tuple[str,str]
    dictionary: dict[str,list[str]]

    total_tests: int = 0
    streak: int = 0
    missed_words: list[str] = field(default_factory = list[str])
    recent_words: list[str] = field(default_factory = list[str])
    use_recent_words = True

class UserQuit(Exception):
    pass

class UserDefaultSelection(Exception):
    pass

class VocabularyParsingError(Exception):
    pass

FILES_DIR = Path("./memorize_files/")
CLASS_FILE_GLOB_PATTERN = "*.json"
CATEGORY_SELECT_PATTERN = re.compile(r"^(\d+)[.:]((\d+)(-(\d+))?|\*)$")
MINIMUM_STREAK_DISPLAY = 5
DEFAULT_NUMBER_OF_ROUNDS = 10
RECENT_WORDS_COUNT = 10

T = TypeVar('T')

def filter_exists(iterable: Iterable[T | None]) -> Iterable[T]:
    return (o for o in iterable if o is not None)

def json_to_str(json_str: Any) -> Optional[str]:
    return json_str if isinstance(json_str, str) else None

def json_to_list_str(json_ls: list) -> Optional[list[str]]:
    return json_ls if all(isinstance(o, str) for o in json_ls) else None

def json_to_str_or_list_str(json_s: Any) -> Optional[str | list[str]]:
    return json_to_list_str(json_s) \
            if isinstance(json_s, list) \
            else json_to_str(json_s)

def json_to_entry(json_obj: Any) -> Optional[CategoryEntry]:
    '''Attempt to convert JSON object to CategoryEntry object'''
    if not isinstance(json_obj, dict):
        return None

    data_as_tuple = [(json_to_str(k), json_to_str_or_list_str(v))
                     for k,v in json_obj.items()]

    return CategoryEntry({
        k:v for k,v in data_as_tuple
        if k is not None and v is not None})

def category_type_str_to_enum(category_type: str) -> CategoryType:
    '''Convert JSON category type strings to enum values'''
    str_map = {
            "vocabulary": CategoryType.Vocabulary }
    return str_map.get(category_type, CategoryType.Unknown)

def json_to_category(json_obj: Any) -> Optional[Category]:
    '''Attempt to convert JSON object to Category object'''
    if not isinstance(json_obj, dict):
        return None

    name = json_obj.get("category_name", None)
    if not isinstance(name, str):
        return None

    type_ = json_obj.get("category_type", None)
    if not isinstance(type_, str):
        return None

    json_entries = json_obj.get("category_contents", None)
    if not isinstance(json_entries, list):
        return None

    contents = [json_to_entry(json_entry) for json_entry in json_entries]
    return Category(
            name,
            category_type_str_to_enum(type_),
            list(filter_exists(contents))
            )

def json_to_class(json_obj: Any) -> Optional[Class]:
    '''Attempt to convert JSON object to Class object'''
    if not isinstance(json_obj, dict):
        return None

    name = json_obj.get("class_name", None)
    if not isinstance(name, str):
        return None

    json_categories = json_obj.get("categories", None)
    if not isinstance(json_categories, list):
        return None

    categories = [json_to_category(json_category) for json_category in json_categories]
    return Class(name, list(filter_exists(categories)))

def load_class_file(path: Path) -> Any:
    result: Any = None
    with open(path) as file:
        result = json.load(file)
    return result

def load_classes() -> list[Class]:
    class_file_paths = FILES_DIR.glob(CLASS_FILE_GLOB_PATTERN)
    json_classes = [load_class_file(path) for path in class_file_paths]
    classes = [json_to_class(json_class) for json_class in json_classes]
    return list(filter_exists(classes))

def print_classes_summary(classes: list[Class]) -> None:
    '''Print summary of loaded classes'''
    ...

# note that indices in the selection are 1-based
def print_category_selection_screen(classes: list[Class]) -> None:
    print("The following classes are available:\n")
    for class_index,class_ in enumerate(classes):
        print(f"{class_index + 1}. {class_.name}")
        for category_index,category in enumerate(class_.categories):
            print(f"\t{class_index + 1}.{category_index + 1} {category.name}")

        print()

# note that indices in the selection are 1-based
def selection_string_to_indices(response: str, classes: list[Class]) -> list[tuple[int,int]]:
    '''Parse selection string into category indices'''
    max_class_index = len(classes) - 1

    choices: set[tuple[int,int]] = set()
    for selection in response.split():
        match = CATEGORY_SELECT_PATTERN.match(selection)
        if match is None:
            print(f"'{selection} is an invalid selection")
            continue

        cls_idx, wild, cat_start, _, cat_end = match.groups()
        class_index = int(cls_idx) - 1 # can't fail because pattern always matches digits
        if class_index < 0 or class_index > max_class_index:
            print(f"Class {class_index} is out of range (maximum is {max_class_index})")
            continue

        range_: Iterable[int]
        if wild == '*':
            range_ = range(0, len(classes[class_index].categories))
        elif cat_end is not None:
            range_ = range(int(cat_start) - 1, int(cat_end)) # range doesn't include stop
        else:
            range_ = range(int(cat_start) - 1, int(cat_start))

        for category_index in range_:
            choices.add((class_index,category_index))

    if len(choices) == 0:
        print("No selection could be made")
        raise UserQuit

    return sorted(choices)

def select_categories_from_classes_interactively(classes: list[Class]) -> list[Category]:
    '''Prompt user to select categories from list'''
    print_category_selection_screen(classes)
    print("Enter your selection: ('q' quits) ", end = '')
    response = input()
    if response.lower() == 'q':
        raise UserQuit

    if response == '':
        raise UserDefaultSelection

    indices = selection_string_to_indices(response, classes)
    return [classes[class_index].categories[category_index]
            for class_index,category_index in indices]

def select_default_categories(classes: list[Class]) -> list[Category]:
    '''Default category selection'''
    print("Selecting everything...")
    categories: list[Category] = []
    for class_ in classes:
        categories += class_.categories
    return categories

DictionaryEntry = namedtuple("DictionaryEntry", "languages translation words")

def vocab_entry_to_dictionary_entry(entry: CategoryEntry) -> DictionaryEntry:
    '''Create entry for language dictionary (languages, translation, words)'''
    data = entry.data
    keys = list(data.keys())
    if len(keys) != 2:
        raise VocabularyParsingError(f"Vocab entry is structured incorrectly: {data=}")

    # depends implicitly on data values being str | list[str]
    #   two assumptions:
    #       - there are only two variants
    #       - the list variant is always a list of strings
    if isinstance(data[keys[0]], list) and isinstance(data[keys[1]], list):
        raise VocabularyParsingError(f"Vocab entry is structured incorrectly: {data=}")
    elif isinstance(data[keys[0]], list):
        return DictionaryEntry((keys[0],keys[1]), data[keys[1]], data[keys[0]])
    elif isinstance(data[keys[1]], list):
        return DictionaryEntry((keys[1],keys[0]), data[keys[0]], data[keys[0]])
    else:
        raise VocabularyParsingError(f"Vocab entry is structured incorrectly: {data=}")

LanguagesKey = tuple[str,str]

def make_language_dictionary(categories: list[Category]) -> dict[LanguagesKey, dict[str, list[str]]]:
    '''Create language dictionary for practice session'''
    dispatch_type_map = {
            CategoryType.Vocabulary: vocab_entry_to_dictionary_entry,
            }

    dictionary: dict[LanguagesKey, dict[str, list[str]]] = {}
    def get_language_dict(languages: LanguagesKey) -> dict[str, list[str]]:
        results = dictionary.get(languages, None)
        if results is None:
            results = {}
            dictionary[languages] = results

        return results

    for category in categories:
        convert_fn = dispatch_type_map.get(category.type_, None)
        if convert_fn is None:
            print(f"Category '{category.name}' has an unknown type")
            continue

        for entry in category.contents:
            languages, translation, words = convert_fn(entry)
            lang_dict = get_language_dict(languages)
            lang_dict[translation] = words

    return dictionary

def select_language_interactively(languages_keys: list[LanguagesKey]) -> LanguagesKey:
    '''Prompt user to select the session language'''
    if len(languages_keys) == 1:
        key = languages_keys[0]
        print(f"Selecting {key[1]} -> {key[0]}")
        return key

    print("Select a language pair:")
    for index,key in enumerate(languages_keys):
        print(f"\t{index + 1}. {key[1]} -> {key[0]}")

    print()
    choice: int | None = None
    while choice is None:
        response = ''
        try:
            print("Enter your selection: ('q' quits) ", end = '')
            response = input()

            if response.lower() == 'q':
                raise UserQuit

            choice = int(response)
            if choice < 1 or choice > len(languages_keys):
                print(f"Choice out of range: {choice}")
                choice = None

        except ValueError:
            print(f"Invalid response '{response}'")

    return languages_keys[choice - 1]

def configure_session_interactively(classes: list[Class]) -> PracticeSession:
    '''Configure the practice session through interactively prompting the user'''
    try:
        categories = select_categories_from_classes_interactively(classes)
    except UserDefaultSelection:
        categories = select_default_categories(classes)

    dictionary = make_language_dictionary(categories)
    languages = select_language_interactively(list(dictionary.keys()))
    return PracticeSession(categories, languages, dictionary[languages])

def ask_rounds() -> int:
    '''Prompt user for number of rounds from selection'''
    selection = (5,10, 20, 50)
    selection_strings = tuple(f"{n} rounds" for n in selection)
    print("How many rounds?")
    print(f"\t1. {selection_strings[0]}\t\t2. {selection_strings[1]}")
    print(f"\t3. {selection_strings[2]}\t\t4. {selection_strings[3]}")
    print()

    choice = None
    while choice is None:
        response = ''
        try:
            print("Enter your selection: ('q' quits) ", end = '')
            response = input()

            if response == '':
                print(f"Defaulting to {DEFAULT_NUMBER_OF_ROUNDS} rounds\n")
                return DEFAULT_NUMBER_OF_ROUNDS

            if response.lower() == 'q':
                raise UserQuit

            choice = int(response)
            if choice < 1 or choice > 4:
                if choice in selection:
                    print()
                    return choice

                print(f"Choice out of range: {choice}")
                choice = None

        except ValueError:
            print(f"Invalid response: '{response}'")

    print()
    return selection[choice - 1]

def congratulation() -> str:
    '''Random congratulation'''
    congratulations = (
            "That is correct!",
            "Correct!",
            "Well done!",
            "This is proof of your genius",
            )
    return random.choice(congratulations)

def comiseration() -> str:
    '''Random comiseration'''
    comiserations = (
            "Too bad!",
            "Too difficult?",
            "Oofie-doodle",
            "You didn't get that one"
            )
    return random.choice(comiserations)

def add_to_recent_words(word: str, session: PracticeSession) -> None:
    '''Add word to list of recent words, trimming the list if required'''
    if not session.use_recent_words:
        return

    if len(list(session.dictionary.keys())) <= RECENT_WORDS_COUNT:
        session.use_recent_words = False
        return

    session.recent_words.append(word)
    if len(session.recent_words) > RECENT_WORDS_COUNT:
        session.recent_words.pop(0)

def get_random_word(session: PracticeSession) -> str:
    '''Get random word that hasn't recently been seen'''
    fn = lambda: random.choice(list(session.dictionary.keys()))
    word = fn()
    while word in session.recent_words:
        word = fn()

    add_to_recent_words(word, session)
    return word

def play_memorize_round(session: PracticeSession) -> None:
    '''Play round of Memorize'''
    word = get_random_word(session)
    answers = session.dictionary[word]

    if session.streak > MINIMUM_STREAK_DISPLAY:
        print(f"{'Streak':>30}: {session.streak}")

    print(f"{'Your word is':>30}: {word}")
    guesses_left = 3
    display_guesses = lambda: f"{guesses_left} guesses" \
            if guesses_left > 1 else "1 guess"

    session.total_tests += 1

    while guesses_left > 0:
        display_prompt = f"Answer ({display_guesses()} left)"
        print(f"{display_prompt:>30}: ", end = '')
        response = input()

        if response == '':
            print("Do you want to quit? (y/n) ", end = '')
            response = input()
            if response.lower() == 'y':
                raise UserQuit

            continue

        if response in answers:
            session.streak += 1

            print(f"\n{congratulation()}")
            if len(answers) > 1:
                other_answers = (answer for answer in answers if answer != response)
                print(f"Other answers could have been {' or '.join(other_answers)}")

            print()
            return

        else:
            print(f"{'Incorrect':>30}")
            session.streak = 0
            guesses_left -= 1

    if len(answers) == 1:
        print(f"\n{comiseration()}\nThe correct answer was {answers[0]}\n")
    else:
        print(f"\n{comiseration()}\nThe correct answers were {' or '.join(answers)}\n")

    if word not in session.missed_words:
        session.missed_words.append(word)

def play_memorize_game(session: PracticeSession) -> None:
    '''Play Memorize game'''
    rounds_left = ask_rounds()
    while rounds_left > 0:
        play_memorize_round(session)
        rounds_left -= 1

        if rounds_left == 0:
            print("Play more? (y/n) ", end = '')
            response = input()
            rounds_left = ask_rounds() if response.lower() == 'y' else 0

def main_terminal_mode(classes: list[Class]) -> None:
    print_classes_summary(classes)

    try:
        session = configure_session_interactively(classes)
        play_memorize_game(session)

    except UserQuit:
        print("Quitting...")
        return

    print(f"Total tests: {session.total_tests}")
    if len(session.missed_words) == 0:
        print("There were no missed words")
    else:
        print(f"Missed words:")
        for word in session.missed_words:
            print(f"\t{word}")

    input()

TUI_KEY_DOWN  = curses.KEY_DOWN                                         # type: ignore
TUI_KEY_UP    = curses.KEY_UP                                           # type: ignore
TUI_KEY_ENTER = (curses.KEY_ENTER, curses.ascii.NL, curses.ascii.CR)    # type: ignore

# TODO: move to class section
@dataclass
class CheckboxMenuEntry:
    text: str
    enabled: bool = field(default = False, kw_only = True)
    rendered_cursor_pos: tuple[int,int] = (-1, -1)

# TODO: move to class section
@dataclass
class CheckboxMenu:
    title: str
    entries: list[CheckboxMenuEntry] = field(default_factory = list[CheckboxMenuEntry])

# TODO move to class section
@dataclass
class TuiContext:
    stdscr: curses.window   # type: ignore

    is_running: bool = False
    cursor: tuple[int,int] = (0,0)
    draw_stack: list[Callable[[Self], None]] = field(
            default_factory = list[Callable[[Self], None]])
    variables: dict[str, Any] = field(default_factory = dict[str, Any])
    callback_map: dict[int, Callable[[Self], None]] = field(
            default_factory = dict[int, Callable[[Self], None]])

POST_DO_NOTHING = lambda _,__: None

# TODO move to class section
@dataclass
class TuiRenderTarget:
    text_render_fn: Callable[[], Iterable[str]]
    post_render_fn: Callable[[int, int], None] = POST_DO_NOTHING
    start_line: int = -1

# TODO move to class section
@dataclass
class TuiLayout:
    tui: TuiContext
    centered_x: bool
    centered_y: bool
    padding: int

    offset_x: int = 0
    offset_y: int = 0
    items: list[TuiRenderTarget] = field(default_factory = list[TuiRenderTarget])

def init_tui_context(stdscr: curses.window):    # type: ignore
    # set raw mode
    curses.raw()    # type: ignore

    # clear and refresh on initialisation
    stdscr.clear()
    stdscr.refresh()

    # define application colours NOTE: hardcoded for now
    curses.start_color()                                        # type: ignore
    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)  # type: ignore
    curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)   # type: ignore
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_WHITE) # type: ignore

    return TuiContext(stdscr)

def get_tui_screen_size(tui: TuiContext) -> tuple[int,int]:
    '''Get the maxy,maxx for the TUI'''
    return tui.stdscr.getmaxyx()

def make_tui_variable(
        tui: TuiContext,
        variable_name: str,
        initial_value: Any
        ) -> bool:
    '''Create a variable with type in the TUI context

    Return False if variable already exists'''
    if tui.variables.get(variable_name, None) is not None:
        return False

    tui.variables[variable_name] = initial_value
    return True

def make_tui_int_variable(tui: TuiContext, variable_name: str, initial_value: int) -> bool:
    '''Create a integer variable in the TUI context

    Return False if variable already exists'''
    # TODO remove code duplication with make_tui_variable
    if tui.variables.get(variable_name, None) is not None:
        return False

    tui.variables[variable_name] = initial_value
    return True

def get_tui_var(tui: TuiContext, variable_name: str) -> Any:
    '''Return value of variable in TUI context, or None if variable is unknown'''
    return tui.variables.get(variable_name, None)

def get_tui_int_variable(tui: TuiContext, variable_name: str) -> Optional[int]:
    '''Return value of integer variable in TUI context, or None if variable
    is unknown'''
    value = tui.variables.get(variable_name, None)
    return value if isinstance(value, int) else None

def set_tui_int_variable(tui: TuiContext, variable_name: str, value: int) -> bool:
    '''Set the value of variable in Tui context

    Return False if variable does not exist or is not an integer'''
    var_val = tui.variables.get(variable_name, None)
    if not isinstance(var_val, int):
        return False

    tui.variables[variable_name] = value
    return True

def map_key_callback(
        tui: TuiContext,
        key_code: int,
        callback: Callable[[TuiContext], None]
        ) -> bool:
    '''Map a key to a callback

    Return False if mapping already exists'''
    if tui.callback_map.get(key_code, None) is not None:
        return False

    tui.callback_map[key_code] = callback
    return True

def map_keys_callback(
        tui: TuiContext,
        key_codes: Iterable[int],
        callback: Callable[[TuiContext], None]
        ) -> bool:
    '''Attempt to map all provided keys to a callback

    Return False if any mapping fails'''
    map_fn = lambda k: map_key_callback(tui, k, callback)
    return all(map_fn(k) for k in key_codes)

def tui_begin_draw(tui: TuiContext):
    '''Prepare TUI context for drawing the next screen state'''
    tui.draw_stack.clear()

def tui_end_draw(tui: TuiContext):
    '''Call drawing callbacks stored in the context'''
    for draw_call in tui.draw_stack:
        draw_call(tui)

def tui_clear_screen(tui: TuiContext):
    '''Clear the TUI'''
    tui.stdscr.clear()

def tui_refresh_screen(tui: TuiContext):
    '''Refresh the TUI'''
    tui.stdscr.refresh()

def clear_screen(tui: TuiContext):
    '''Draw call for clearing the screen

    Use this between tui_begin_draw and tui_end_draw instead of tui_clear_screen'''
    def draw_call(t: TuiContext):
        tui_clear_screen(t)

    tui.draw_stack.append(draw_call)

def refresh_screen(tui: TuiContext):
    '''Draw call for refreshing the screen

    Use this between tui_begin_draw and tui_end_draw instead of tui_refresh_screen'''
    def draw_call(t: TuiContext):
        tui_refresh_screen(t)

    tui.draw_stack.append(draw_call)

def tui_draw_text(tui: TuiContext, text: str, x: int, y: int):
    '''Draw text starting at position on screen'''
    tui.stdscr.addstr(y, x, text)

def tui_move_cursor(tui: TuiContext, x: int, y: int):
    '''Move cursor to position'''
    max_y,max_x = tui.stdscr.getmaxyx()
    if x >= 0 and x <= max_x and y >= 0 and y <= max_y:
        tui.stdscr.move(y, x)

def tui_mainloop(tui: TuiContext) -> None:
    tui.is_running = True
    while tui.is_running:
        key = tui.stdscr.getch()
        callback = tui.callback_map.get(key, None)
        if callback is not None:
            callback(tui)

def tui_pause(tui: TuiContext) -> None:
    tui.is_running = False

def make_tui_layout(
        tui: TuiContext, *,
        centered_x: bool = False,
        centered_y: bool = False,
        padding   : int  = 0
        ) -> TuiLayout:
    '''Create automatic layout'''
    if padding < 0:
        raise ValueError(f"TuiLayout padding must be >= 0: {padding}")
    layout = TuiLayout(tui, centered_x, centered_y, padding)
    tui.draw_stack.append(lambda t: draw_layout(t, layout))
    return layout

def draw_layout(tui: TuiContext, layout: TuiLayout):
    '''Render layout to TUI'''
    lines: list[str] = []
    max_width: int = 0

    for item_index,item in enumerate(layout.items):
        if item_index != 0 and layout.padding != 0:
            lines.extend(itertools.repeat("", layout.padding))

        item.start_line = len(lines)
        item_text = item.text_render_fn()
        max_item_width = max(len(l) for l in item_text)
        if max_item_width > max_width:
            max_width = max_item_width

        lines.extend(item_text)

    width = max_width
    height = len(lines)
    screen_height,screen_width = get_tui_screen_size(tui)

    # TODO: implement display offsets

    if height > screen_height:
        lines = lines[:screen_height]
        height = screen_height

    if width > screen_width:
        width = screen_width

    start_y = (screen_height - height) // 2 if layout.centered_y else 0
    start_x = (screen_width - width) // 2 if layout.centered_x else 0

    for line_index,line in enumerate(lines):
        tui_draw_text(tui, line[:width], start_x, start_y + line_index)

    for item in layout.items:
        item.post_render_fn(start_x, start_y + item.start_line)

def add_text_to_layout(layout: TuiLayout, text: str):
    '''Add text as item to layout'''
    layout.items.append(TuiRenderTarget(lambda: [ text ]))

def add_checkbox_menu_to_layout(layout: TuiLayout, menu: CheckboxMenu):
    '''Render menu as text for layout item'''
    entry_button_cursor_pairs: list[tuple[CheckboxMenuEntry, tuple[int, int]]] = []
    lines: list[str] = []

    def render() -> list[str]:
        entry_button_cursor_pairs.clear()
        lines.clear()
        lines.append(menu.title)
        for entry_index, entry in enumerate(menu.entries):
            button = "[X]" if entry.enabled else "[ ]"
            lines.append(f"{button} {entry.text}")
            entry_button_cursor_pairs.append((entry, (1, entry_index + 1)))
        return lines

    def post_render(x: int, y: int):
        for entry, cursor in entry_button_cursor_pairs:
            cursor_x, cursor_y = cursor
            entry.rendered_cursor_pos = (x + cursor_x, y + cursor_y)

    layout.items.append(TuiRenderTarget(render, post_render))

def select_categories_from_classes_screen(tui: TuiContext, classes: list[Class]) -> list[Category]:
    '''Display TUI screen for selecting categories from classes'''
    # NOTE: this is just first pass code and should be refactored
    title_str = "The following classes are available:"

    make_tui_variable(tui, "menus", list())
    menus: list = get_tui_var(tui, "menus")
    for class_index,class_ in enumerate(classes):
        class_id = class_index + 1
        menu = CheckboxMenu(f"{class_id}. {class_.name}")
        menus.append(menu)
        for category_index,category in enumerate(class_.categories):
            category_id = category_index + 1
            # set everything enabled by default
            menu.entries.append(CheckboxMenuEntry(f"{class_id}.{category_id} {category.name}", enabled = True))

    # TODO could use a with block for draw calls
    tui_begin_draw(tui)
    clear_screen(tui)

    layout = make_tui_layout(tui, centered_x = True, centered_y = True, padding = 1)
    add_text_to_layout(layout, title_str)
    for menu in menus:
        add_checkbox_menu_to_layout(layout, menu)

    refresh_screen(tui)
    tui_end_draw(tui)

    make_tui_int_variable(tui, "selected_class_index", 0)
    make_tui_int_variable(tui, "selected_category_index", 0)

    def selection_indices(t: TuiContext) -> tuple[int,int]:
        class_index = get_tui_int_variable(t, "selected_class_index")
        if class_index is None:
            raise RuntimeError("TUI variable missing: class_index")
        category_index = get_tui_int_variable(t, "selected_category_index")
        if category_index is None:
            raise RuntimeError("TUI variable missing: class_index")
        return (class_index,category_index)

    def set_selection(t: TuiContext, selection: tuple[int,int]):
        class_index, category_index = selection
        set_tui_int_variable(t, "selected_class_index", class_index)
        set_tui_int_variable(t, "selected_category_index", category_index)

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

    def on_quit(_):
        raise UserQuit

    def on_down(t: TuiContext):
        menus: list[CheckboxMenu] = get_tui_var(t, "menus")
        menu_idx,entry_idx = menu_selection_next(menus, selection_indices(t))
        set_selection(t, (menu_idx, entry_idx))
        x,y = menus[menu_idx].entries[entry_idx].rendered_cursor_pos
        tui_move_cursor(t, x, y)

    def on_up(t: TuiContext):
        menus: list[CheckboxMenu] = get_tui_var(t, "menus")
        menu_idx,entry_idx = menu_selection_prev(menus, selection_indices(t))
        set_selection(t, (menu_idx, entry_idx))
        x,y = menus[menu_idx].entries[entry_idx].rendered_cursor_pos
        tui_move_cursor(t, x, y)

    def on_enter(t: TuiContext):
        tui_pause(t)

    def on_space(t: TuiContext):
        menus: list[CheckboxMenu] = get_tui_var(t, "menus")
        menu_idx, entry_idx = selection_indices(t)
        selected_entry = menus[menu_idx].entries[entry_idx]
        selected_entry.enabled = not selected_entry.enabled

        tui_end_draw(t)
        tui_move_cursor(t, *selected_entry.rendered_cursor_pos)

    map_key_callback(tui, ord('q'), on_quit)
    map_key_callback(tui, TUI_KEY_DOWN, on_down)
    map_key_callback(tui, TUI_KEY_UP, on_up)
    map_key_callback(tui, ord(' '), on_space)
    map_keys_callback(tui, TUI_KEY_ENTER, on_enter)

    start_x, start_y = menus[0].entries[0].rendered_cursor_pos
    tui_move_cursor(tui, start_x, start_y)

    tui_mainloop(tui)

    # filter classes and categories by menu entry
    categories: list[Category] = []
    for menu_index,menu in enumerate(menus):
        if not isinstance(menu, CheckboxMenu):
            continue

        for entry_index,entry in enumerate(menu.entries):
            if entry.enabled:
                categories.append(classes[menu_index].categories[entry_index])

    return categories

def select_language_screen(
        tui: TuiContext,
        languages_keys: list[LanguagesKey]
        ) -> LanguagesKey:
    '''Display menu for selecting languages from list'''
    ...

def configure_session_tui(tui: TuiContext, classes: list[Class]) -> PracticeSession:
    '''Configure the practice session with TUI controls'''
    # NOTE: this is just first pass code and should be refactored
    categories = select_categories_from_classes_screen(tui, classes)
    dictionary = make_language_dictionary(categories)
    # TODO remove testing code
    tui_draw_text(tui, f"{dictionary!r}", 0, 0)
    tui_mainloop(tui)
    languages = select_language_screen(tui, list(dictionary.keys()))
    return PracticeSession(categories, languages, dictionary[languages])

def play_memorize_game_tui(session: PracticeSession) -> None:
    ...

def display_summary_screen(session: PracticeSession) -> None:
    ...

def main_tui_mode(stdscr: curses.window, classes: list[Class]) -> None: # type: ignore
    tui = init_tui_context(stdscr)
    try:
        session = configure_session_tui(tui, classes)
        play_memorize_game_tui(session)
        display_summary_screen(session)

    except UserQuit:
        return

argparser = ArgumentParser(description = "Practice learning languages")
argparser.add_argument('--no-curses', action = 'store_true', help = \
        "Do not use curses python library")

def main():
    program_args = argparser.parse_args()
    classes = load_classes()
    if not USE_CURSES or program_args.no_curses:
        main_terminal_mode(classes)

    else:
        curses.wrapper(main_tui_mode, classes)  # type: ignore

if __name__ == "__main__":
    main()

