from enum import Enum, auto
from dataclasses import dataclass, field
from collections import namedtuple

import random

from prog_signal import VocabularyParsingError

RECENT_WORDS_COUNT = 10
MINIMUM_STREAK_DISPLAY = 5

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

DictionaryEntry = namedtuple("DictionaryEntry", "languages translation words")
LanguagesKey = tuple[str,str]

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

