from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Iterable, TypeVar

import json
import re
import importlib.util
import random

from data import (
        Category, Class, LanguagesKey, PracticeSession, make_language_dictionary,
        get_random_word, MINIMUM_STREAK_DISPLAY, congratulation, comiseration)
from prog_signal import UserQuit, UserDefaultSelection
from memorize_tui import run_main_tui_mode

USE_CURSES: bool
if importlib.util.find_spec("curses") is not None:  # does curses exist
    USE_CURSES = True
else:
    USE_CURSES = False

FILES_DIR = Path("./memorize_files/")
CLASS_FILE_GLOB_PATTERN = "*.json"
CATEGORY_SELECT_PATTERN = re.compile(r"^(\d+)[.:]((\d+)(-(\d+))?|\*)$")
DEFAULT_NUMBER_OF_ROUNDS = 10

T = TypeVar('T')

def load_class_file(path: Path) -> Any:
    result: Any = None
    with open(path) as file:
        result = json.load(file)
    return result

def load_classes() -> list[Class]:
    class_file_paths = sorted(FILES_DIR.glob(CLASS_FILE_GLOB_PATTERN))
    json_classes = [load_class_file(path) for path in class_file_paths]
    classes = [Class.from_dict(json_class) for json_class in json_classes]
    return [class_ for class_ in classes if class_ is not None]

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

g_shuffled_words: list[str] = []

def get_shuffled_word(session: PracticeSession) -> str:
    '''Get random word by shuffling words'''
    global g_shuffled_words
    if len(g_shuffled_words) == 0:
        g_shuffled_words = list(session.dictionary.keys())
        random.shuffle(g_shuffled_words)

    return g_shuffled_words.pop()

def play_memorize_round(session: PracticeSession) -> None:
    '''Play round of Memorize'''
    #word = get_random_word(session)
    word = get_shuffled_word(session)
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
            run_main_tui_mode(classes)

        except UserQuit:
            print("Quitting...")
            return

if __name__ == "__main__":
    main()

