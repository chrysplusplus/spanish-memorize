from argparse import ArgumentParser
from collections import namedtuple
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional, Any, Iterable, Self, TypeVar, Sequence

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

# ==============================================================================
# TUI SECTION
# ==============================================================================

TUI_KEY_DOWN      = (curses.KEY_DOWN,)      # type: ignore
TUI_KEY_UP        = (curses.KEY_UP,)        # type: ignore
TUI_KEY_ENTER     = (
        (curses.KEY_ENTER,),                # type: ignore
        (curses.ascii.NL,),                 # type: ignore
        (curses.ascii.CR,)                  # type: ignore
        )
TUI_KEY_BACKSPACE = (curses.KEY_BACKSPACE,) # type: ignore

TUI_KEY_EVENT = ""

def validate_keystr(key_str: str) -> str:
    '''Trim and validate key representation

    Raise ValueError if key representation is invalid'''
    key_str = key_str.lower()
    if len(key_str) == 0 or not key_str.isprintable():
        raise ValueError(f"Invalid key character: {key_str}")
    return key_str[0]

TuiKey = tuple[int, ...]

def as_key(key_str: str) -> TuiKey:
    '''Convert string representing keyboard character to key code

    Raise ValueError if key representation is invalid'''
    return (ord(validate_keystr(key_str)),)

def as_ctrl_key(key_str: str) -> TuiKey:
    '''Convert string to control key code

    For example: as_ctrl_key('c') would yield the key code for Ctrl-C

    Raise ValueError if key representation is invalid'''
    return (curses.ascii.ctrl(ord(validate_keystr(key_str))),)   # type: ignore

def key_to_str(key: TuiKey) -> str:
    '''Convert TuiKey to printable string'''
    if len(key) == 1:
        return curses.keyname(key[0]).decode("utf-8")   # type: ignore
    else:
        return bytes(key).decode("utf-8")

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

@dataclass
class MenuEntry:
    text: str
    rendered_cursor_pos: tuple[int,int] = (-1, -1)

@dataclass
class Menu:
    title: str
    entries: list[MenuEntry] = field(default_factory= list[MenuEntry])
    selected_index: int = -1

# TODO move to class section
@dataclass
class TuiContext:
    stdscr: curses.window   # type: ignore

    # TODO change to non dataclass
    is_running: bool = False
    cursor: tuple[int,int] = (0,0)
    draw_stack: list[Callable[[Self], None]] = field(
            default_factory = list[Callable[[Self], None]])
    variables: dict[str, Any] = field(default_factory = dict[str, Any])
    callbacks: dict[str, list[Callable[[Self, TuiKey], bool]]] = field(
            default_factory = dict[str, list[Callable[[Self, TuiKey], bool]]])
    event_queue: list[str] = field(default_factory = list[str])

@dataclass
class TuiAcceleratorMap:
    tui: TuiContext
    handler: Callable[[TuiContext, TuiKey], bool]
    key_map: dict[TuiKey, Callable[[TuiContext], None]] = field(
            default_factory = dict[TuiKey, Callable[[TuiContext], None]])

POST_DO_NOTHING = lambda _,__: None

# TODO move to class section
@dataclass
class TuiRenderTarget:
    text_render_fn: Callable[[], Iterable[str]]
    post_render_fn: Callable[[int, int], None] = POST_DO_NOTHING
    start_x: int = -1
    start_y: int = -1

# TODO move to class section
@dataclass
class TuiLayout:
    tui: TuiContext
    centered_x: bool
    centered_y: bool
    padding:    int
    min_width:  int
    min_height: int

    offset_x: int = 0
    offset_y: int = 0
    items: list[TuiRenderTarget] = field(default_factory = list[TuiRenderTarget])

def init_tui_context(stdscr: curses.window) -> TuiContext:  # type: ignore
    '''Initialise TUI and return context object'''
    # set raw mode
    curses.raw()    # type: ignore

    # set nodelay mode
    stdscr.nodelay(True)

    # use default colours
    curses.use_default_colors() # type: ignore

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

class SetTuiVariableResult(Enum):
    Ok = auto()
    VariableDoesExist = auto()
    TypeMismatch = auto()

def set_tui_variable(tui: TuiContext, variable_name: str, value: Any) -> SetTuiVariableResult:
    if variable_name not in tui.variables.keys():
        return SetTuiVariableResult.VariableDoesExist

    current_var_val = tui.variables[variable_name]
    if type(value) != type(current_var_val):
        return SetTuiVariableResult.TypeMismatch

    tui.variables[variable_name] = value
    return SetTuiVariableResult.Ok

def destroy_tui_variable(tui: TuiContext, variable_name: str) -> None:
    '''Remove variable from TUI context

    If variable is not known to the context, fail silently'''
    if variable_name in tui.variables.keys():
        del tui.variables[variable_name]

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

def tui_add_callback(
        tui: TuiContext,
        event_type: str,
        callback: Callable[[TuiContext, TuiKey], bool]
        ) -> bool:
    '''Add callback for handling the specified event type

    If succcessful, callback is added at the top of the stack and so will be
    called before the previous items in the stack during the event callback
    stage

    callback should be a callable that accepts a TuiContext and an int as its
    parameters, which represent the current TUI context and the key input that
    triggered the current event respectively, and returns a bool, which if True
    indicates that the next event callback should be used. It is generally
    recommended to return True from the callback.

    Return False if callback was previously added for this event type'''
    callback_stack = tui.callbacks.get(event_type, None)
    if callback_stack is None:
        callback_stack = [ callback ]
        tui.callbacks[event_type] = callback_stack
        return True
    elif callback in callback_stack:
        return False
    else:
        callback_stack.insert(0, callback)
        return True

def tui_remove_callback(
        tui:TuiContext,
        event_type: str,
        callback: Callable[[TuiContext, TuiKey], bool]
        ) -> None:
    '''Remove registered callback handlers'''
    callback_stack = tui.callbacks.get(event_type, None)
    if callback_stack is None: return
    if callback in callback_stack: callback_stack.remove(callback)

def tui_begin_draw(tui: TuiContext) -> None:
    '''Prepare TUI context for drawing the next screen state'''
    tui.draw_stack.clear()

def tui_end_draw(tui: TuiContext) -> None:
    '''Call drawing callbacks stored in the context'''
    for draw_call in tui.draw_stack:
        draw_call(tui)

def tui_redraw(tui: TuiContext) -> None:
    '''Redraw the screen using the previous drawing callbacks'''
    tui_end_draw(tui)

def tui_clear_screen(tui: TuiContext) -> None:
    '''Clear the TUI'''
    tui.stdscr.clear()

def tui_refresh_screen(tui: TuiContext) -> None:
    '''Refresh the TUI'''
    tui.stdscr.refresh()

def clear_screen(tui: TuiContext) -> None:
    '''Draw call for clearing the screen

    Use this between tui_begin_draw and tui_end_draw instead of tui_clear_screen'''
    def draw_call(t: TuiContext):
        tui_clear_screen(t)

    tui.draw_stack.append(draw_call)

def refresh_screen(tui: TuiContext) -> None:
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

TuiEventCallbackStack = list[Callable[[TuiContext, TuiKey], bool]]

def _tui_process_event_callback(t: TuiContext, k: TuiKey, s: TuiEventCallbackStack) -> None:
    '''Process event callback'''
    for callback in s:
        do_next = callback(t, k)
        if not do_next:
            break

def _tui_process_event_queue(t: TuiContext, k: TuiKey) -> None:
    '''Process event queue'''
    while len(t.event_queue) != 0:
        event_type = t.event_queue.pop(0)
        callback_stack = t.callbacks.get(event_type, None)
        if callback_stack is None:
            continue
        _tui_process_event_callback(t, k, callback_stack)

def _tui_get_key(t: TuiContext) -> TuiKey:
    '''Get key from typeahead'''
    key_bytes: list[int] = []
    key = t.stdscr.getch()
    while key != -1:
        key_bytes.append(key)
        key = t.stdscr.getch()

    return tuple(key_bytes)

def tui_mainloop(tui: TuiContext) -> None:
    '''Run main loop for handling user input'''
    tui.is_running = True
    while tui.is_running:
        key = _tui_get_key(tui)
        if len(key) != 0:
            tui.event_queue.append(TUI_KEY_EVENT)
        _tui_process_event_queue(tui, key)

def tui_pause(tui: TuiContext) -> None:
    '''Return control back to program code until next mainloop'''
    tui.is_running = False

def tui_emit(tui: TuiContext, event_type: str) -> None:
    '''Emit event type to event queue'''
    tui.event_queue.append(event_type)

def tui_add_accelerator_map(tui: TuiContext) -> TuiAcceleratorMap:
    '''Add an accelerator map for creating a layer to process key inputs'''
    key_map: dict[TuiKey, Callable[[TuiContext], None]] = {}

    def handler(t: TuiContext, key: TuiKey) -> bool:
        callback = key_map.get(key, None)
        if callback is not None:
            callback(t)
            return False    # prevent further propagation which might be unexpected

        return True

    tui_add_callback(tui, TUI_KEY_EVENT, handler)
    return TuiAcceleratorMap(tui, handler, key_map)

def tui_destroy_accelerator_map(tui: TuiContext, accel_map: TuiAcceleratorMap) -> None:
    '''Remove the accelerator map from the TUI context

    If accel_map is not a known callback for TUI_KEY_EVENT, then fail silently'''
    callback_stack = tui.callbacks.get(TUI_KEY_EVENT, None)
    if callback_stack is None:
        return

    callback = accel_map.handler
    if callback in callback_stack:
        callback_stack.remove(callback)

def map_key_callback(
        accel_map: TuiAcceleratorMap,
        key_code: TuiKey,
        callback: Callable[[TuiContext], None]
        ) -> bool:
    '''Map a key to a callback

    Return False if mapping already exists'''
    if accel_map.key_map.get(key_code, None) is not None:
        return False

    accel_map.key_map[key_code] = callback
    return True

def map_keys_callback(
        accel_map: TuiAcceleratorMap,
        key_codes: Iterable[TuiKey],
        callback: Callable[[TuiContext], None]
        ) -> bool:
    '''Attempt to map all provided keys to a callback

    Return False if any mapping fails'''
    map_fn = lambda k: map_key_callback(accel_map, k, callback)
    return all(map_fn(k) for k in key_codes)

def make_tui_layout(
        tui: TuiContext, *,
        centered_x: bool = False,
        centered_y: bool = False,
        padding   : int  = 0,
        min_width : int  = -1,
        min_height: int  = -1
        ) -> TuiLayout:
    '''Create automatic layout'''
    if padding < 0:
        raise ValueError(f"TuiLayout padding must be >= 0: {padding}")
    layout = TuiLayout(tui, centered_x, centered_y, padding, min_width, min_height)
    tui.draw_stack.append(lambda t: draw_layout(t, layout))
    return layout

def draw_layout(tui: TuiContext, layout: TuiLayout):
    '''Render layout to TUI'''
    lines: list[str] = []
    max_width: int = 0

    for item_index,item in enumerate(layout.items):
        if item_index != 0 and layout.padding != 0:
            lines.extend(itertools.repeat("", layout.padding))

        item.start_y = len(lines)
        item_text = item.text_render_fn()
        max_item_width = max(len(l) for l in item_text)
        if max_item_width > max_width:
            max_width = max_item_width

        lines.extend(item_text)

    width = max(layout.min_width, max_width)
    height = max(layout.min_height, len(lines))
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
        item.start_y += start_y
        item.start_x = start_x
        item.post_render_fn(item.start_x, item.start_y)

def add_text_to_layout(layout: TuiLayout, text: str) -> TuiRenderTarget:
    '''Add text as item to layout'''
    target = TuiRenderTarget(lambda: [ text ])
    layout.items.append(target)
    return target

def add_checkbox_menu_to_layout(layout: TuiLayout, menu: CheckboxMenu) -> TuiRenderTarget:
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

    target = TuiRenderTarget(render, post_render)
    layout.items.append(target)
    return target

def add_menu_to_layout(layout: TuiLayout, menu: Menu) -> TuiRenderTarget:
    '''Define draw calls to render the menu'''
    entry_button_cursor_pairs: list[tuple[MenuEntry, tuple[int,int]]] = []

    def render() -> list[str]:
        entry_button_cursor_pairs.clear()
        lines: list[str] = []
        lines.append(menu.title)
        for entry_index, entry in enumerate(menu.entries):
            lines.append(f"  {entry.text}")
            entry_button_cursor_pairs.append((entry, (0, entry_index + 1)))
        return lines

    def post_render(x: int, y: int):
        for entry, cursor in entry_button_cursor_pairs:
            cursor_x, cursor_y = cursor
            entry.rendered_cursor_pos = (x + cursor_x, y + cursor_y)

    target = TuiRenderTarget(render, post_render)
    layout.items.append(target)
    return target

def add_eval_to_layout(layout: TuiLayout, eval_fn: Callable[[], str]) -> TuiRenderTarget:
    '''Add text which is evaluated at draw time'''
    target = TuiRenderTarget(lambda: (eval_fn(), ))
    layout.items.append(target)
    return target

def on_quit(_):
    '''Event handler for quitting the program'''
    raise UserQuit

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

    layout = make_tui_layout(tui, centered_x = True, centered_y = True, padding = 1, min_width = 50)
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

        tui_redraw(t)
        tui_move_cursor(t, *selected_entry.rendered_cursor_pos)

    accel_map = tui_add_accelerator_map(tui)
    map_key_callback(accel_map, TUI_KEY_DOWN, on_down)
    map_key_callback(accel_map, TUI_KEY_UP, on_up)
    map_key_callback(accel_map, as_key(' '), on_space)
    map_keys_callback(accel_map, TUI_KEY_ENTER, on_enter)
    map_key_callback(accel_map, as_key('q'), on_quit)

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

    destroy_tui_variable(tui, "menus")
    destroy_tui_variable(tui, "selected_class_index")
    destroy_tui_variable(tui, "selected_category_index")
    tui_destroy_accelerator_map(tui, accel_map)
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
    make_tui_variable(tui, "menu", Menu(title))
    menu: Menu = get_tui_var(tui, "menu")
    for item in items:
        menu.entries.append(MenuEntry(item_display_fn(item)))

    tui_begin_draw(tui)
    clear_screen(tui)
    layout = make_tui_layout(tui, centered_x = True, centered_y = True, padding = 1, min_width = 50)
    add_menu_to_layout(layout, menu)
    refresh_screen(tui)
    tui_end_draw(tui)

    menu.selected_index = start_index

    def menu_get_bounded_selection(menu: Menu, index: int) -> int:
        index = max(0, index)
        index = min(len(menu.entries) - 1, index)
        return index

    def on_down(t: TuiContext):
        menu: Menu = get_tui_var(t, "menu")
        index = menu_get_bounded_selection(menu, menu.selected_index + 1)
        tui_move_cursor(t, *menu.entries[index].rendered_cursor_pos)
        menu.selected_index = index

    def on_up(t: TuiContext):
        menu: Menu = get_tui_var(t, "menu")
        index = menu_get_bounded_selection(menu, menu.selected_index - 1)
        tui_move_cursor(t, *menu.entries[index].rendered_cursor_pos)
        menu.selected_index = index

    def on_enter(t: TuiContext):
        tui_pause(t)

    accel_map = tui_add_accelerator_map(tui)
    map_key_callback(accel_map, TUI_KEY_DOWN, on_down)
    map_key_callback(accel_map, TUI_KEY_UP, on_up)
    map_keys_callback(accel_map, TUI_KEY_ENTER, on_enter)
    map_key_callback(accel_map, as_key('q'), on_quit)

    tui_move_cursor(tui, *menu.entries[menu.selected_index].rendered_cursor_pos)
    tui_mainloop(tui)

    choice = menu.selected_index

    destroy_tui_variable(tui, "menu")
    tui_destroy_accelerator_map(tui, accel_map)
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
    categories = select_categories_from_classes_screen(tui, classes)
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
    make_tui_int_variable(tui, "guesses_left", 3)
    guesses_left = get_tui_int_variable(tui, "guesses_left")
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

    make_tui_variable(tui, "title", display_title(session))
    make_tui_variable(tui, "answer_prompt", f"Answer ({display_guesses(guesses_left)} left):")
    make_tui_variable(tui, "answer_response", "")
    make_tui_variable(tui, "feedback_1", "")
    make_tui_variable(tui, "feedback_2", "")
    make_tui_int_variable(tui, "state", GUESSING)

    # draw calls
    tui_begin_draw(tui)
    clear_screen(tui)

    layout = make_tui_layout(tui, centered_x=True, centered_y=True, min_width = 50)
    add_eval_to_layout(layout, lambda: get_tui_var(tui, "title"))
    add_text_to_layout(layout, "")
    add_text_to_layout(layout, "Your word is:")
    add_text_to_layout(layout, word)
    add_text_to_layout(layout, "")
    add_eval_to_layout(layout, lambda: get_tui_var(tui, "answer_prompt"))

    response_render_target = add_eval_to_layout(
            layout, lambda: get_tui_var(tui, "answer_response"))
    make_tui_variable(tui, "entry", response_render_target)

    add_text_to_layout(layout, "")
    add_eval_to_layout(layout, lambda: get_tui_var(tui, "feedback_1"))
    add_eval_to_layout(layout, lambda: get_tui_var(tui, "feedback_2"))

    refresh_screen(tui)
    tui_end_draw(tui)

    # set initial state
    cursor_x = response_render_target.start_x
    cursor_y = response_render_target.start_y
    tui_move_cursor(tui, cursor_x, cursor_y)

    # event handling
    def move_cursor_to_entry(t: TuiContext):
        response: str = get_tui_var(t, "answer_response")
        entry: TuiRenderTarget = get_tui_var(t, "entry")
        tui_move_cursor(t, x=entry.start_x + len(response), y=entry.start_y)

    def on_entry_key_press(t: TuiContext, k: TuiKey) -> bool:
        state = get_tui_int_variable(t, "state")
        if state != GUESSING:
            return True

        key_str = key_to_str(k)
        current_response: str = get_tui_var(t, "answer_response")
        if k == TUI_KEY_BACKSPACE:
            set_tui_variable(t, "answer_response", current_response[:-1])
            tui_emit(t, "text_changed")
        elif len(key_str) > 1: # key is special key
            pass
        else:
            set_tui_variable(t, "answer_response", current_response + key_str)
            tui_emit(t, "text_changed")
        return True

    def on_text_changed(t: TuiContext, _) -> bool:
        tui_redraw(t)
        move_cursor_to_entry(t)
        return True

    def on_enter(t: TuiContext):
        response: str = get_tui_var(t, "answer_response")
        if len(response) == 0 : return

        state = get_tui_int_variable(t, "state")
        if state == GUESSING:            tui_emit(t, "submit")
        elif state == WAITING_TO_RETRY:  tui_emit(t, "retry")
        elif state == WORD_GUESSED:      tui_emit(t, "finish")
        elif state == WORD_MISSED:       tui_emit(t, "finish")
        else: raise RuntimeError(f"Unknown state in play_memorize_round_tui: {state}")

    def correct(t: TuiContext, response: str):
        session.streak += 1
        set_tui_variable(t, "feedback_1", f"{congratulation()}")
        if len(answers) > 1:
            other_answers = (answer for answer in answers if answer != response)
            set_tui_variable(
                    t,
                    "feedback_2",
                    f"Other answers could have been {' or '.join(other_answers)}")

        set_tui_int_variable(t, "state", WORD_GUESSED)
        tui_redraw(t)
        move_cursor_to_entry(t)

    def wrong(t: TuiContext, _):
        old_streak = session.streak
        session.streak = 0
        if old_streak >= MINIMUM_STREAK_DISPLAY:
            set_tui_variable(t, "title", f"{display_title(session)} | Streak of {old_streak} lost...")

        guesses_left = get_tui_int_variable(t, "guesses_left")
        if guesses_left is None:
            raise RuntimeError("Variable missing: guesses_left")

        guesses_left -= 1
        if guesses_left == 0:
            set_tui_variable(t, "answer_prompt", f"Answer ({display_guesses(guesses_left)} left):")
            set_tui_variable(t, "feedback_1", f"{comiseration()}")
            set_tui_variable(
                    t, "feedback_2",
                    f"The correct answer was {answers[0]}"
                    if len(answers) == 1
                    else f"The correct answers were {' or '.join(answers)}")
            set_tui_int_variable(t, "state", WORD_MISSED)
            tui_redraw(t)
            move_cursor_to_entry(t)

        else:
            set_tui_variable(t, "answer_prompt", f"Answer ({display_guesses(guesses_left)} left):")
            set_tui_variable(t, "feedback_1", "Incorrect")
            set_tui_variable(t, "feedback_2", "Prese Enter to retry...")
            set_tui_int_variable(t, "guesses_left", guesses_left)
            tui_redraw(t)
            move_cursor_to_entry(t)

            set_tui_int_variable(t, "state", WAITING_TO_RETRY)

    def on_submit(t: TuiContext, _) -> bool:
        response: str = get_tui_var(t, "answer_response")
        if response.lower().strip() in answers: correct(t, response)
        else: wrong(t, response)
        return True

    def on_retry(t: TuiContext, _) -> bool:
        guesses_left = get_tui_int_variable(t, "guesses_left")
        set_tui_variable(t, "answer_prompt", f"Answer ({display_guesses(guesses_left)} left):")
        set_tui_variable(t, "answer_response", "")
        set_tui_variable(t, "feedback_1", "")
        set_tui_variable(t, "feedback_2", "")
        set_tui_int_variable(t, "state", GUESSING)
        tui_redraw(t)
        move_cursor_to_entry(t)
        return True

    def on_finish(t: TuiContext, _) -> bool:
        state = get_tui_int_variable(t, "state")
        if state is None:
            raise RuntimeError("Variable missing: state")
        elif state == WORD_MISSED and word not in session.missed_words:
            session.missed_words.append(word)

        tui_pause(t)
        return True

    tui_add_callback(tui, TUI_KEY_EVENT, on_entry_key_press)
    tui_add_callback(tui, "text_changed", on_text_changed)
    tui_add_callback(tui, "submit", on_submit)
    tui_add_callback(tui, "retry", on_retry)
    tui_add_callback(tui, "finish", on_finish)

    accel_map = tui_add_accelerator_map(tui)
    map_keys_callback(accel_map, TUI_KEY_ENTER, on_enter)

    tui_mainloop(tui)

    # cleanup
    destroy_tui_variable(tui, "guesses_left")
    destroy_tui_variable(tui, "title")
    destroy_tui_variable(tui, "answer_prompt")
    destroy_tui_variable(tui, "answer_response")
    destroy_tui_variable(tui, "feedback_1")
    destroy_tui_variable(tui, "feedback_2")
    destroy_tui_variable(tui, "state")
    destroy_tui_variable(tui, "entry")
    tui_remove_callback(tui, TUI_KEY_EVENT, on_entry_key_press)
    tui_remove_callback(tui, "text_changed", on_text_changed)
    tui_remove_callback(tui, "submit", on_submit)
    tui_remove_callback(tui, "retry", on_retry)
    tui_remove_callback(tui, "finish", on_finish)
    tui_destroy_accelerator_map(tui, accel_map)

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
    tui_begin_draw(tui)
    clear_screen(tui)

    layout = make_tui_layout(tui, centered_x=True, centered_y=True, min_width=50)
    add_text_to_layout(layout, f"Total test: {session.total_tests}")
    if len(session.missed_words) == 0:
        add_text_to_layout(layout, "There were no missed words")
    else:
        add_text_to_layout(layout, "Missed words:")
        for word in session.missed_words:
            add_text_to_layout(layout, f"    {word}")

    add_text_to_layout(layout, "")
    add_text_to_layout(layout, "Press any key to quit...")

    refresh_screen(tui)
    tui_end_draw(tui)

    # event handling
    def on_key_press(t: TuiContext, _):
        tui_pause(t)
        return True

    tui_add_callback(tui, TUI_KEY_EVENT, on_key_press)
    tui_mainloop(tui)

    # cleanup
    tui_remove_callback(tui, TUI_KEY_EVENT, on_key_press)

def main_tui_mode(stdscr: curses.window, classes: list[Class]) -> None: # type: ignore
    tui = init_tui_context(stdscr)
    accel_map = tui_add_accelerator_map(tui)
    map_key_callback(accel_map, as_ctrl_key('c'), on_quit)

    session = configure_session_tui(tui, classes)
    play_memorize_game_tui(tui, session)
    display_summary_screen(tui, session)

argparser = ArgumentParser(description = "Practice learning languages")
argparser.add_argument('--no-curses', action = 'store_true', help = \
        "Do not use curses python library")

def main():
    program_args = argparser.parse_args()
    classes = load_classes()
    if not USE_CURSES or program_args.no_curses:
        print("Using terminal mode -- some features may be missing")
        main_terminal_mode(classes)

    else:
        try:
            curses.wrapper(main_tui_mode, classes)  # type: ignore

        except UserQuit:
            print("Quitting...")
            return

if __name__ == "__main__":
    main()

