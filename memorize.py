from collections import namedtuple
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Any, Iterable

import json
import random
import re
import sys

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
    missed_words: list[str] = field(default_factory = list)
    recent_words: list[str] = field(default_factory = list)
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

def filter_exists[T](iterable: Iterable[T]) -> Iterable[T]:
    return filter(lambda o: o is not None, iterable)

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
    choices: list[tuple[int,int]] = []
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

type LanguagesKey = tuple[str,str]

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
        try:
            print("Enter your selection: ('q' quits) ", end = '')
            response = input()

            if response.lower() == 'q':
                raise UserQuit

            choice = int(response)
            if response < 1 or response > len(languages_keys):
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
    print(f"\t1. {selection[0]}\t\t2. {selection[1]}")
    print(f"\t3. {selection[2]}\t\t4. {selection[3]}")
    print()

    choice = None
    while choice is None:
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

def main():
    classes = load_classes()
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

if __name__ == "__main__":
    main()
